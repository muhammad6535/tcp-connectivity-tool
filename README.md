# TCP Connectivity Test Tool

A small, dependency-free Python CLI that repeatedly tests TCP connectivity to a
host and port, records every attempt to CSV, and prints a pass/fail summary with
connect-time statistics.

It was built as a hands-on QA/networking project: sockets, DNS, TCP error
semantics, repeatable test scenarios, machine-readable evidence, and CI-friendly
exit codes — using only the Python standard library.

## Why this is more than "call connect()"

- **Correct metric.** `connect_time_ms` measures the TCP handshake with
  `time.perf_counter()` (monotonic). It is **not** ping latency and **not**
  application response time.
- **Honest semantics.** A success means the TCP port accepted a connection. It
  does **not** prove the HTTP application behind it is healthy.
- **Stable error taxonomy.** Failures are classified (`CONNECTION_REFUSED`,
  `TIMEOUT`, `DNS_ERROR`, ...) so results can be asserted on in CI.
- **Crash-safe evidence.** The CSV is flushed after every attempt, and `Ctrl+C`
  preserves completed results.
- **Output-error safety.** An unwritable or failing CSV returns exit `3` and
  never claims the file was saved.
- **Automation contract.** Exit codes distinguish success, test failures, usage
  errors, and interruption.

## Features

- Arguments for host, port, attempts, timeout, interval, and CSV output path
- One TCP connect + immediate close per attempt
- Per-attempt timestamp (UTC, ISO 8601), resolved address, result, connect time,
  and error details
- Handles refused connections, timeouts, DNS failures, and other socket errors
- Summary: total, successes, failures, success rate, average/min/max successful
  connect time (`N/A` when nothing succeeded), and a failure breakdown
- Argument validation (including non-finite numbers) with clear messages and
  exit code `2`
- Graceful `Ctrl+C` that keeps completed rows and exits `130`
- 27 automated tests, no third-party packages

## Requirements

- Python **3.10+** (uses `X | Y` type unions)
- Linux, macOS, or Windows
- No `pip install` required

Tested on **Ubuntu 24.04.5 LTS** with **Python 3.12.3**.

## Quick start

```bash
git clone https://github.com/muhammad6535/tcp-connectivity-tool.git
cd tcp-connectivity-tool

# Terminal 1: start a local TCP listener
python3 -m http.server 8000 --bind 127.0.0.1

# Terminal 2: run 5 checks, 1 second apart
python3 tcp_check.py 127.0.0.1 8000 -n 5 -t 2 -i 1 -o results.csv
```

Example output:

```text
[1/5] SUCCESS 0.304 ms (127.0.0.1)
[2/5] SUCCESS 0.076 ms (127.0.0.1)
[3/5] SUCCESS 0.137 ms (127.0.0.1)
[4/5] SUCCESS 0.089 ms (127.0.0.1)
[5/5] SUCCESS 0.148 ms (127.0.0.1)

===== Summary =====
Target: 127.0.0.1:8000
Attempts completed: 5/5
Successes: 5
Failures: 0
Success rate: 100.00%
Avg successful connect time: 0.151 ms
Min/Max successful connect time: 0.076 / 0.304 ms
Results CSV: /path/to/results.csv
```

> A successful TCP connection only proves that the port accepted a connection.
> The HTTP application can still be unhealthy (for example, returning HTTP 500).

## CLI reference

```text
usage: tcp_check.py [-h] [-n ATTEMPTS] [-t TIMEOUT] [-i INTERVAL] [-o OUTPUT]
                    host port
```

| Argument | Default | Description |
|---|---|---|
| `host` | required | Hostname or IP address |
| `port` | required | TCP port, `1`–`65535` |
| `-n`, `--attempts` | `5` | Number of connection attempts, `>= 1` |
| `-t`, `--timeout` | `2.0` | Finite TCP connect timeout in seconds, `> 0` |
| `-i`, `--interval` | `1.0` | Finite seconds between attempts, `>= 0` |
| `-o`, `--output` | `results.csv` | CSV output path (parent directory must exist) |

More examples:

```bash
# Failures on a stopped server (expect CONNECTION_REFUSED, not TIMEOUT)
python3 tcp_check.py 127.0.0.1 8000 -n 3 -i 0.5 -o refused.csv

# DNS failure (the .invalid TLD never resolves)
python3 tcp_check.py does-not-exist.invalid 80 -n 2 -o dns.csv

# Real connect timeout against a blackhole address
python3 tcp_check.py 192.0.2.1 81 -n 2 -t 1 -i 0.2 -o timeout.csv
```

## What the timing means

`connect_time_ms` covers **only** the TCP three-way handshake:

```
client                         server
  | ---- SYN ------------------> |
  | <--- SYN-ACK --------------- |
  | ---- ACK ------------------> |   connect() returns here
```

- Measured with `time.perf_counter()` — monotonic, unaffected by wall-clock/NTP
  changes.
- Starts immediately before `connect()` and stops when the handshake completes.
- **Excludes DNS resolution** and any application/TLS/HTTP exchange.
- Therefore it is not "ping latency" (ICMP) and not "response time" (L7).

`--timeout` applies to `connect()`. Hostname resolution uses the operating
system resolver's own timeout, which this tool does not override.

## CSV schema

One row per attempt, written and flushed immediately:

| Column | Example | Meaning |
|---|---|---|
| `attempt` | `1` | 1-based attempt number |
| `timestamp_utc` | `2026-11-06T13:46:39.470Z` | Attempt start, UTC ISO 8601 (ms) |
| `target` | `127.0.0.1:8000` | Host and port as given |
| `resolved_address` | `127.0.0.1` | IP the hostname resolved to (empty on DNS failure) |
| `result` | `SUCCESS` / `FAILURE` | Handshake outcome |
| `connect_time_ms` | `0.304` | Handshake time in ms; empty on failure |
| `error_type` | `CONNECTION_REFUSED` | Stable failure category; empty on success |
| `error_detail` | `[Errno 111] Connection refused` | Human-readable detail |

Error types: `CONNECTION_REFUSED`, `TIMEOUT`, `DNS_ERROR`, `HOST_UNREACHABLE`,
`NETWORK_UNREACHABLE`, `CONNECTION_ERROR`, `UNKNOWN_ERROR`.

Each run **overwrites** the output file and writes a header, so every CSV is a
self-contained result artifact.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | All completed attempts succeeded |
| `1` | At least one attempt failed |
| `2` | Invalid arguments / output path |
| `3` | CSV could not be written (results not saved) |
| `130` | Interrupted by `Ctrl+C` (completed rows preserved) |

These make the tool usable in CI: a job fails when connectivity fails, while
usage errors stay distinguishable from test failures.

## Test scenarios

Full expected-vs-observed evidence: [`docs/TEST_RESULTS.md`](docs/TEST_RESULTS.md).

| # | Scenario | Expected | Observed |
|---|---|---|---|
| 1 | Server running on `127.0.0.1:8000` | Success, exit `0` | 5/5 SUCCESS, avg 0.151 ms, exit `0` |
| 2 | Server stopped | `CONNECTION_REFUSED`, exit `1` | 3/3 refused, avg `N/A`, exit `1` |
| 3 | Unused port `8999` | `CONNECTION_REFUSED`, exit `1` | 2/2 refused, exit `1` |
| 4 | Stop server during checks | Success → failure transition, **completed** CSV, exit `1` | 3 SUCCESS then 7 refused, 10/10 rows, exit `1` |
| 5 | Invalid arguments | Clear message, exit `2` | 4/4 cases exit `2` |
| 6 | Blackhole address (`192.0.2.1`) | `TIMEOUT`, exit `1` | 2/2 `TIMEOUT`, exit `1` |
| 7 | Invalid hostname | `DNS_ERROR`, exit `1` | 2/2 `DNS_ERROR`, exit `1` |
| 8 | `Ctrl+C` during a run | **Partial** CSV, exit `130` | 1/5 rows saved, exit `130` |
| 9 | Unwritable CSV path | Clear error, exit `3`, no false "saved" claim | Error printed, exit `3` |

> Stopping the server does **not** shorten the run: every attempt still executes,
> so the CSV is complete and contains both successes and failures, and the exit
> code is `1`. Only `Ctrl+C` stops early, which leaves a partial CSV and exits
> `130`.

Reproduce scenarios 1–6 end to end:

```bash
./scripts/run_scenarios.sh          # writes the CSVs in samples/
```

### Connection refused vs timeout

A **stopped local server usually produces `Connection refused`**, not a timeout:
the kernel answers the SYN with a TCP RST because nothing is listening on the
port. A **timeout** means no reply arrived at all — commonly a firewall dropping
packets, a blackholed route, or a host that is down/unreachable.

Do not confuse the two when writing test expectations.

### Testing timeouts without changing firewall rules

This project uses `192.0.2.1` (`TEST-NET-1`, RFC 5737 — reserved for
documentation, normally routed nowhere). It reliably produced `TIMEOUT` here:

```bash
python3 tcp_check.py 192.0.2.1 81 -n 2 -t 1 -o samples/sample_timeout.csv
```

If you *want* to test a firewall `DROP` explicitly, that requires `sudo` and is
intentionally **not automated** here:

```bash
# OPTIONAL, manual, requires sudo. Add then remove the rule.
sudo iptables -A INPUT -p tcp --dport 9000 -j DROP
python3 tcp_check.py 127.0.0.1 9000 -n 2 -t 1 -o drop.csv
sudo iptables -D INPUT -p tcp --dport 9000 -j DROP
```

## Automated tests

```bash
python3 -m unittest discover -s tests -v
```

Result on this machine: **27 tests, all passing**. One real-timeout test is
opt-in; enable it with:

```bash
RUN_TIMEOUT_TEST=1 python3 -m unittest discover -s tests -v
```

The suite covers: real successful connects, refused ports, DNS failures, error
classification, summary math (`N/A` included), CSV mapping, exit codes, invalid
arguments (including `NaN`/`Infinity`), output-write failures, and `Ctrl+C`
preservation (via a mocked interrupt).

`pytest` is optional and also works if installed:

```bash
python3 -m pytest tests -v
```

## Project layout

```text
tcp-connectivity-tool/
├── tcp_check.py                 # CLI tool, stdlib only
├── tests/
│   └── test_tcp_check.py        # 27 unittest tests
├── scripts/
│   ├── start_server.sh          # local TCP listener helper
│   └── run_scenarios.sh         # reproduces scenarios 1-6
├── samples/
│   ├── sample_success.csv
│   ├── sample_server_stopped.csv
│   ├── sample_unused_port.csv
│   ├── sample_transition.csv
│   ├── sample_timeout.csv
│   └── sample_dns_error.csv
├── docs/
│   └── TEST_RESULTS.md          # expected vs observed evidence
├── .gitignore
└── LICENSE
```

## Design notes

- **Flush per row**: `Ctrl+C` or a crash cannot discard completed attempts.
- **Empty `connect_time_ms` on failure**: averages never get polluted by zeros.
- **Iterate all resolved addresses**: tries each address returned by
  `getaddrinfo()` until one connects (IPv6 then IPv4, etc.).
- **Close immediately**: the tool probes reachability; it does not hold sessions.
- **UTC timestamps**: unambiguous when results are compared across machines.
- **Validation before any I/O**: bad input fails fast with exit `2`.

## Troubleshooting

| Symptom | Likely cause | Check |
|---|---|---|
| `OSError: [Errno 98] Address already in use` | Port already bound | `ss -ltnp 'sport = :8000'` or `lsof -i :8000` |
| `CONNECTION_REFUSED` on localhost | Nothing listening on that port | Start the server; confirm the port |
| `DNS_ERROR` | Typo, no resolver, or `.invalid` host | `getent hosts <name>` |
| `TIMEOUT` | Packets dropped/blackholed | Try another host; check routing/firewall |
| Permission denied on low port | Ports `< 1024` need privileges | Use an unprivileged port like `8000` |

## Known limitations

- Connectivity only; it does not validate application health, TLS, or HTTP.
- Sequential attempts (no concurrency).
- DNS resolver timeout is outside the `--timeout` control.
- Only the first successfully connected address is recorded per attempt.
- No IPv6-only or multi-homed-specific test coverage was performed.

## Exercises

1. **JSON output** — add `--format json` alongside CSV. *Learn:* output contracts.
2. **App-level check** — after TCP success, send an HTTP request with `urllib`
   and record the status code. *Learn:* why L4 success ≠ L7 health.
3. **Fail fast** — add `--fail-fast` that stops after the first failure.
   *Learn:* test-runner semantics and exit codes.
4. **Append mode with `run_id`** — keep history across runs. *Learn:* data
   modeling and idempotency.
5. **Concurrency** — check N targets with `concurrent.futures.ThreadPoolExecutor`.
   *Learn:* concurrency, timing, and resource cleanup.
6. **Retry with backoff** — retry only retryable error types. *Learn:* error
   taxonomy in practice.
7. **Packet-level view** — capture a run with `sudo tcpdump -i lo port 8000` and
   explain SYN/SYN-ACK/ACK. *Learn:* protocol troubleshooting.
8. **Packaging** — add `pyproject.toml` and a `tcp-check` console script.
   *Learn:* distributable Python tooling.

## License

MIT — see [LICENSE](LICENSE).
