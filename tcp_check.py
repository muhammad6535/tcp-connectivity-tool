#!/usr/bin/env python3
"""TCP connectivity test tool (standard library only).

Repeatedly attempts a TCP connection to HOST:PORT, records every result to CSV,
and prints a summary.

What "success" means:
    The TCP three-way handshake completed, i.e. the target port accepted a
    connection. This proves reachability of the TCP port, not that the
    application behind it (HTTP, database, ...) is healthy.

What connect_time_ms means:
    Time from just before connect() until the handshake completed, measured
    with time.perf_counter() (monotonic). DNS resolution is NOT included.

Usage:
    python3 tcp_check.py 127.0.0.1 8000 -n 5 -t 2 -i 1 -o results.csv
"""

from __future__ import annotations

import argparse
import csv
import errno
import math
import socket
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

EXIT_OK = 0
EXIT_FAILURES = 1
EXIT_USAGE = 2
EXIT_OUTPUT_ERROR = 3
EXIT_INTERRUPTED = 130


@dataclass
class AttemptResult:
    """Outcome of a single TCP connection attempt."""

    attempt: int
    timestamp_utc: str
    host: str
    port: int
    resolved_address: str
    success: bool
    connect_time_ms: float | None
    error_type: str
    error_detail: str


def utc_timestamp() -> str:
    """Current UTC time as ISO 8601 with millisecond precision, e.g. ...Z."""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def classify_error(exc: BaseException) -> tuple[str, str]:
    """Map a socket exception to a stable, report-friendly error type."""
    detail = " ".join(str(exc).split()) or exc.__class__.__name__

    # gaierror is a subclass of OSError, so check it first.
    if isinstance(exc, socket.gaierror):
        return "DNS_ERROR", f"{detail} (errno {exc.errno})"
    if isinstance(exc, TimeoutError):
        return "TIMEOUT", detail
    if isinstance(exc, ConnectionRefusedError):
        return "CONNECTION_REFUSED", detail
    if isinstance(exc, OSError):
        if exc.errno == errno.EHOSTUNREACH:
            return "HOST_UNREACHABLE", detail
        if exc.errno == errno.ENETUNREACH:
            return "NETWORK_UNREACHABLE", detail
        return "CONNECTION_ERROR", detail
    return "UNKNOWN_ERROR", detail


def _failure(
    attempt: int,
    timestamp: str,
    host: str,
    port: int,
    resolved_address: str,
    error_type: str,
    error_detail: str,
) -> AttemptResult:
    return AttemptResult(
        attempt=attempt,
        timestamp_utc=timestamp,
        host=host,
        port=port,
        resolved_address=resolved_address,
        success=False,
        connect_time_ms=None,
        error_type=error_type,
        error_detail=error_detail,
    )


def check_once(host: str, port: int, timeout: float, attempt: int = 1) -> AttemptResult:
    """Perform one TCP connectivity check.

    Resolves the hostname, tries each returned address in order, and returns
    on the first successful connect. Only the successful connect is timed.
    The socket is always closed: we are probing, not keeping a session open.
    """
    timestamp = utc_timestamp()

    try:
        addrinfos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        error_type, detail = classify_error(exc)
        return _failure(attempt, timestamp, host, port, "", error_type, detail)

    if not addrinfos:
        return _failure(
            attempt, timestamp, host, port, "", "DNS_ERROR", "no addresses returned"
        )

    last_exc: OSError | None = None
    last_address = ""

    for family, socktype, proto, _canonname, sockaddr in addrinfos:
        last_address = str(sockaddr[0])
        sock = socket.socket(family, socktype, proto)
        try:
            sock.settimeout(timeout)
            start = time.perf_counter()
            sock.connect(sockaddr)
        except OSError as exc:
            last_exc = exc
            continue
        else:
            connect_time_ms = (time.perf_counter() - start) * 1000.0
            return AttemptResult(
                attempt=attempt,
                timestamp_utc=timestamp,
                host=host,
                port=port,
                resolved_address=last_address,
                success=True,
                connect_time_ms=connect_time_ms,
                error_type="",
                error_detail="",
            )
        finally:
            sock.close()

    if last_exc is not None:
        error_type, detail = classify_error(last_exc)
        return _failure(
            attempt, timestamp, host, port, last_address, error_type, detail
        )
    return _failure(
        attempt, timestamp, host, port, last_address, "UNKNOWN_ERROR", "connect failed"
    )


def build_summary(results: list[AttemptResult]) -> dict:
    """Compute aggregate numbers for the summary (kept side-effect free for tests)."""
    total = len(results)
    successes = sum(1 for r in results if r.success)
    failures = total - successes
    successful_times = [r.connect_time_ms for r in results if r.success]

    return {
        "total": total,
        "successes": successes,
        "failures": failures,
        "success_rate": (successes / total * 100.0) if total else None,
        "avg_ms": statistics.mean(successful_times) if successful_times else None,
        "min_ms": min(successful_times) if successful_times else None,
        "max_ms": max(successful_times) if successful_times else None,
        "error_counts": Counter(r.error_type for r in results if not r.success),
    }


def print_summary(
    results: list[AttemptResult],
    host: str,
    port: int,
    requested_attempts: int,
    csv_path: Path,
    interrupted: bool,
    csv_saved: bool,
) -> None:
    summary = build_summary(results)

    print()
    print("===== Summary =====")
    print(f"Target: {host}:{port}")
    print(f"Attempts completed: {summary['total']}/{requested_attempts}")
    if interrupted:
        print("Run interrupted by Ctrl+C - partial results were saved.")
    print(f"Successes: {summary['successes']}")
    print(f"Failures: {summary['failures']}")

    if summary["success_rate"] is None:
        print("Success rate: N/A (no completed attempts)")
        print("Avg successful connect time: N/A")
    else:
        print(f"Success rate: {summary['success_rate']:.2f}%")
        if summary["avg_ms"] is None:
            print("Avg successful connect time: N/A (no successful connections)")
        else:
            print(f"Avg successful connect time: {summary['avg_ms']:.3f} ms")
            print(
                "Min/Max successful connect time: "
                f"{summary['min_ms']:.3f} / {summary['max_ms']:.3f} ms"
            )

    if summary["error_counts"]:
        print("Failure breakdown:")
        for error_type, count in summary["error_counts"].most_common():
            print(f"  {error_type}: {count}")

    print(f"Results CSV: {csv_path.resolve()}" if csv_saved
          else f"CSV NOT SAVED (write failed): {csv_path}")


CSV_FIELDS = [
    "attempt",
    "timestamp_utc",
    "target",
    "resolved_address",
    "result",
    "connect_time_ms",
    "error_type",
    "error_detail",
]


def result_to_row(result: AttemptResult) -> dict:
    """Flatten an AttemptResult into CSV-friendly values."""
    return {
        "attempt": result.attempt,
        "timestamp_utc": result.timestamp_utc,
        "target": f"{result.host}:{result.port}",
        "resolved_address": result.resolved_address,
        "result": "SUCCESS" if result.success else "FAILURE",
        "connect_time_ms": (
            "" if result.connect_time_ms is None else f"{result.connect_time_ms:.3f}"
        ),
        "error_type": result.error_type,
        "error_detail": result.error_detail,
    }


def port_number(value: str) -> int:
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"port must be an integer, got {value!r}")
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError(f"port must be 1-65535, got {port}")
    return port


def positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"must be an integer, got {value!r}")
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1, got {number}")
    return number


def non_negative_float(value: str) -> float:
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"must be a number, got {value!r}")
    if not math.isfinite(number):
        raise argparse.ArgumentTypeError(f"must be a finite number, got {value!r}")
    if number < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0, got {number}")
    return number


def positive_float(value: str) -> float:
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"must be a number, got {value!r}")
    if not math.isfinite(number):
        raise argparse.ArgumentTypeError(f"must be a finite number, got {value!r}")
    if number <= 0:
        raise argparse.ArgumentTypeError(f"must be > 0, got {number}")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tcp_check.py",
        description=(
            "Repeatedly test TCP connectivity to HOST:PORT and save each attempt "
            "to CSV. connect_time_ms measures the TCP handshake only, using a "
            "monotonic timer; it is not ping latency or application response time."
        ),
    )
    parser.add_argument("host", help="target hostname or IP address")
    parser.add_argument("port", type=port_number, help="target TCP port (1-65535)")
    parser.add_argument(
        "-n",
        "--attempts",
        type=positive_int,
        default=5,
        help="number of connection attempts (default: 5)",
    )
    parser.add_argument(
        "-t",
        "--timeout",
        type=positive_float,
        default=2.0,
        help="finite TCP connect timeout in seconds, > 0 (default: 2.0)",
    )
    parser.add_argument(
        "-i",
        "--interval",
        type=non_negative_float,
        default=1.0,
        help="finite seconds to wait between attempts, >= 0 (default: 1.0)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="results.csv",
        help="output CSV path (default: results.csv)",
    )
    return parser


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> Path:
    """Extra validation that argparse types cannot express cleanly."""
    args.host = args.host.strip()
    if not args.host:
        parser.error("host must not be empty")
    if "\0" in args.output:
        parser.error("output path must not contain a null byte")

    try:
        csv_path = Path(args.output).expanduser()
        path_exists = csv_path.exists()
        is_directory = csv_path.is_dir()
        parent_exists = csv_path.parent.exists()
    except (OSError, ValueError) as exc:
        parser.error(f"invalid output path {args.output!r}: {exc}")

    if path_exists and is_directory:
        parser.error(f"output path is a directory: {csv_path}")
    if not parent_exists:
        parser.error(f"output directory does not exist: {csv_path.parent}")

    return csv_path


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    csv_path = validate_args(parser, args)

    results: list[AttemptResult] = []
    interrupted = False
    output_error = False

    try:
        csv_file = csv_path.open("w", newline="", encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(
            f"tcp_check.py: error: cannot write CSV '{csv_path}': {exc}",
            file=sys.stderr,
        )
        return EXIT_OUTPUT_ERROR

    try:
        with csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
            try:
                writer.writeheader()
                csv_file.flush()

                for attempt in range(1, args.attempts + 1):
                    result = check_once(args.host, args.port, args.timeout, attempt)
                    results.append(result)
                    writer.writerow(result_to_row(result))
                    csv_file.flush()

                    if result.success:
                        print(
                            f"[{attempt}/{args.attempts}] SUCCESS "
                            f"{result.connect_time_ms:.3f} ms "
                            f"({result.resolved_address})"
                        )
                    else:
                        print(
                            f"[{attempt}/{args.attempts}] FAILURE "
                            f"{result.error_type}: {result.error_detail}"
                        )

                    if attempt < args.attempts and args.interval > 0:
                        time.sleep(args.interval)
            except OSError as exc:
                output_error = True
                print(
                    f"tcp_check.py: error: failed to write CSV '{csv_path}': {exc}",
                    file=sys.stderr,
                )
    except KeyboardInterrupt:
        interrupted = True
        print("\nCtrl+C received - stopping after completed attempts.")
    except OSError as exc:
        output_error = True
        print(
            f"tcp_check.py: error: failed to write CSV '{csv_path}': {exc}",
            file=sys.stderr,
        )
    finally:
        print_summary(
            results,
            args.host,
            args.port,
            args.attempts,
            csv_path,
            interrupted,
            csv_saved=not output_error,
        )

    if output_error:
        return EXIT_OUTPUT_ERROR
    if interrupted:
        return EXIT_INTERRUPTED
    return EXIT_FAILURES if any(not r.success for r in results) else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
