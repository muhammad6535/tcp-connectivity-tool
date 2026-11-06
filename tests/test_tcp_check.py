#!/usr/bin/env python3
"""Unit and integration tests for tcp_check.py (stdlib only).

Run from the project root:
    python3 -m unittest discover -s tests -v
"""

import csv
import errno
import io
import os
import socket
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import tcp_check  # noqa: E402  (import after sys.path setup)


class LocalListener:
    """A real TCP listener on 127.0.0.1 for integration tests."""

    def __enter__(self) -> "LocalListener":
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.port = self.sock.getsockname()[1]
        return self

    def __exit__(self, *_exc) -> None:
        self.sock.close()


def closed_local_port() -> int:
    """Return a port that is currently not listening on 127.0.0.1."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def read_csv_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def success_result(attempt: int = 1) -> tcp_check.AttemptResult:
    return tcp_check.AttemptResult(
        attempt=attempt,
        timestamp_utc=tcp_check.utc_timestamp(),
        host="127.0.0.1",
        port=8000,
        resolved_address="127.0.0.1",
        success=True,
        connect_time_ms=0.25,
        error_type="",
        error_detail="",
    )


class TestCheckOnce(unittest.TestCase):
    def test_success_against_real_listener(self) -> None:
        with LocalListener() as listener:
            result = tcp_check.check_once("127.0.0.1", listener.port, 2.0)

        self.assertTrue(result.success)
        self.assertIsNotNone(result.connect_time_ms)
        self.assertGreaterEqual(result.connect_time_ms, 0.0)
        self.assertEqual(result.resolved_address, "127.0.0.1")
        self.assertEqual(result.error_type, "")

    def test_connection_refused_when_port_closed(self) -> None:
        port = closed_local_port()
        result = tcp_check.check_once("127.0.0.1", port, 2.0)

        self.assertFalse(result.success)
        self.assertIsNone(result.connect_time_ms)
        self.assertEqual(result.error_type, "CONNECTION_REFUSED")

    def test_dns_error_for_invalid_hostname(self) -> None:
        result = tcp_check.check_once("does-not-exist.invalid", 80, 1.0)

        self.assertFalse(result.success)
        self.assertEqual(result.error_type, "DNS_ERROR")
        self.assertEqual(result.resolved_address, "")

    @unittest.skipUnless(
        os.environ.get("RUN_TIMEOUT_TEST") == "1",
        "set RUN_TIMEOUT_TEST=1 to attempt a real connect timeout",
    )
    def test_timeout_against_blackhole_address(self) -> None:
        # 192.0.2.0/24 is TEST-NET-1 (RFC 5737): normally routed nowhere.
        result = tcp_check.check_once("192.0.2.1", 81, 0.5)

        self.assertFalse(result.success)
        self.assertEqual(result.error_type, "TIMEOUT")


class TestClassifyError(unittest.TestCase):
    def test_timeout(self) -> None:
        self.assertEqual(tcp_check.classify_error(TimeoutError("timed out"))[0], "TIMEOUT")

    def test_refused(self) -> None:
        exc = ConnectionRefusedError(errno.ECONNREFUSED, "Connection refused")
        self.assertEqual(tcp_check.classify_error(exc)[0], "CONNECTION_REFUSED")

    def test_dns(self) -> None:
        exc = socket.gaierror(-2, "Name or service not known")
        self.assertEqual(tcp_check.classify_error(exc)[0], "DNS_ERROR")

    def test_host_unreachable(self) -> None:
        exc = OSError(errno.EHOSTUNREACH, "No route to host")
        self.assertEqual(tcp_check.classify_error(exc)[0], "HOST_UNREACHABLE")

    def test_network_unreachable(self) -> None:
        exc = OSError(errno.ENETUNREACH, "Network is unreachable")
        self.assertEqual(tcp_check.classify_error(exc)[0], "NETWORK_UNREACHABLE")

    def test_other_os_error(self) -> None:
        exc = OSError(errno.EIO, "I/O error")
        self.assertEqual(tcp_check.classify_error(exc)[0], "CONNECTION_ERROR")


class TestSummary(unittest.TestCase):
    def test_empty_results(self) -> None:
        summary = tcp_check.build_summary([])

        self.assertEqual(summary["total"], 0)
        self.assertEqual(summary["successes"], 0)
        self.assertIsNone(summary["success_rate"])
        self.assertIsNone(summary["avg_ms"])

    def test_all_success(self) -> None:
        results = [success_result(1), success_result(2)]
        summary = tcp_check.build_summary(results)

        self.assertEqual(summary["success_rate"], 100.0)
        self.assertEqual(summary["avg_ms"], 0.25)
        self.assertEqual(summary["failures"], 0)

    def test_no_success_gives_none_average(self) -> None:
        failure = tcp_check.AttemptResult(
            1, tcp_check.utc_timestamp(), "h", 1, "", False, None,
            "CONNECTION_REFUSED", "refused",
        )
        summary = tcp_check.build_summary([failure])

        self.assertEqual(summary["success_rate"], 0.0)
        self.assertIsNone(summary["avg_ms"])
        self.assertEqual(summary["error_counts"]["CONNECTION_REFUSED"], 1)

    def test_mixed_results_average_uses_successes_only(self) -> None:
        ok = success_result(1)
        ok.connect_time_ms = 1.0
        failure = tcp_check.AttemptResult(
            2, tcp_check.utc_timestamp(), "h", 1, "", False, None,
            "TIMEOUT", "timed out",
        )
        summary = tcp_check.build_summary([ok, failure])

        self.assertEqual(summary["success_rate"], 50.0)
        self.assertEqual(summary["avg_ms"], 1.0)


class TestCsvRow(unittest.TestCase):
    def test_success_row(self) -> None:
        row = tcp_check.result_to_row(success_result())

        self.assertEqual(row["result"], "SUCCESS")
        self.assertEqual(row["connect_time_ms"], "0.250")
        self.assertEqual(row["error_type"], "")

    def test_failure_row_has_empty_connect_time(self) -> None:
        failure = tcp_check.AttemptResult(
            1, tcp_check.utc_timestamp(), "h", 1, "", False, None,
            "DNS_ERROR", "boom",
        )
        row = tcp_check.result_to_row(failure)

        self.assertEqual(row["result"], "FAILURE")
        self.assertEqual(row["connect_time_ms"], "")
        self.assertEqual(row["error_type"], "DNS_ERROR")


class TestMain(unittest.TestCase):
    def test_success_run_writes_csv_and_exits_zero(self) -> None:
        with LocalListener() as listener, tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "results.csv"
            with redirect_stdout(io.StringIO()):
                code = tcp_check.main(
                    ["127.0.0.1", str(listener.port), "-n", "2", "-i", "0", "-o", str(out)]
                )

            self.assertEqual(code, 0)
            rows = read_csv_rows(out)
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(row["result"] == "SUCCESS" for row in rows))
            self.assertTrue(all(float(row["connect_time_ms"]) >= 0 for row in rows))

    def test_failure_run_exits_one_and_reports_na(self) -> None:
        port = closed_local_port()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "results.csv"
            with redirect_stdout(io.StringIO()) as stdout:
                code = tcp_check.main(
                    ["127.0.0.1", str(port), "-n", "2", "-i", "0", "-o", str(out)]
                )

            self.assertEqual(code, 1)
            self.assertIn("Avg successful connect time: N/A", stdout.getvalue())
            rows = read_csv_rows(out)
            self.assertTrue(all(row["result"] == "FAILURE" for row in rows))
            self.assertTrue(all(row["connect_time_ms"] == "" for row in rows))

    def test_invalid_port_exits_two(self) -> None:
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                tcp_check.main(["127.0.0.1", "0"])
        self.assertEqual(ctx.exception.code, 2)

    def test_invalid_attempts_exits_two(self) -> None:
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                tcp_check.main(["127.0.0.1", "8000", "-n", "0"])
        self.assertEqual(ctx.exception.code, 2)

    def test_missing_output_directory_exits_two(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, redirect_stderr(io.StringIO()):
            missing = Path(tmp) / "missing" / "results.csv"
            with self.assertRaises(SystemExit) as ctx:
                tcp_check.main(["127.0.0.1", "8000", "-o", str(missing)])
        self.assertEqual(ctx.exception.code, 2)

    def test_ctrl_c_preserves_completed_rows(self) -> None:
        calls = {"count": 0}

        def fake_check(host, port, timeout, attempt=1):
            calls["count"] += 1
            if calls["count"] == 2:
                raise KeyboardInterrupt
            return success_result(attempt)

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "results.csv"
            with mock.patch.object(tcp_check, "check_once", side_effect=fake_check):
                with redirect_stdout(io.StringIO()) as stdout:
                    code = tcp_check.main(
                        ["127.0.0.1", "8000", "-n", "5", "-i", "0", "-o", str(out)]
                    )

            self.assertEqual(code, 130)
            self.assertIn("Run interrupted by Ctrl+C", stdout.getvalue())
            rows = read_csv_rows(out)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["result"], "SUCCESS")


if __name__ == "__main__":
    unittest.main(verbosity=2)
