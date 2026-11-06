# Test Results — TCP Connectivity Test Tool

Expected vs. observed evidence from an actual run.

## Environment

| Item | Value |
|---|---|
| OS | Ubuntu 24.04.5 LTS |
| Kernel | Linux 7.0.0-42-generic |
| Python | 3.12.3 |
| Test date | 2026-11-06 (UTC) |
| Tool under test | `tcp_check.py` |
| Local target | `127.0.0.1:8000` (`python3 -m http.server`) |
| Working directory | project root |

All commands below were executed from the project root.

## Summary

| ID | Scenario | Expected | Observed | Status |
|---|---|---|---|---|
| TC-01 | Server running on the correct port | Success, exit `0` | 5/5 SUCCESS, avg 0.151 ms, exit `0` | **PASS** |
| TC-02 | Server stopped | `CONNECTION_REFUSED`, exit `1` | 3/3 refused, avg `N/A`, exit `1` | **PASS** |
| TC-03 | Unused port `8999` | `CONNECTION_REFUSED`, exit `1` | 2/2 refused, exit `1` | **PASS** |
| TC-04 | Stop server during repeated checks | SUCCESS rows transition to FAILURE | 3 SUCCESS, then 7 refused; 30% success, exit `1` | **PASS** |
| TC-05 | Invalid arguments | Clear validation message, exit `2` | 4/4 cases exit `2` | **PASS** |
| TC-06 | Connect timeout (blackhole `192.0.2.1`) | `TIMEOUT`, exit `1` | 2/2 `TIMEOUT`, avg `N/A`, exit `1` | **PASS** |
| TC-07 | Hostname resolution failure | `DNS_ERROR`, exit `1` | 2/2 `DNS_ERROR`, empty resolved address, exit `1` | **PASS** |
| TC-08 | `Ctrl+C` during a run | Completed rows preserved, exit `130` | 1/5 rows saved, summary printed, exit `130` | **PASS** |
| TC-09 | Automated test suite | All tests pass | 22 tests OK (timeout test enabled) | **PASS** |

## Evidence

### TC-01 — server running

```text
[1/5] SUCCESS 0.304 ms (127.0.0.1)
[2/5] SUCCESS 0.076 ms (127.0.0.1)
[3/5] SUCCESS 0.137 ms (127.0.0.1)
[4/5] SUCCESS 0.089 ms (127.0.0.1)
[5/5] SUCCESS 0.148 ms (127.0.0.1)

Successes: 5
Failures: 0
Success rate: 100.00%
Avg successful connect time: 0.151 ms
Min/Max successful connect time: 0.076 / 0.304 ms
exit_code=0
```

CSV: [`samples/sample_success.csv`](../samples/sample_success.csv)

### TC-02 — server stopped

```text
[1/3] FAILURE CONNECTION_REFUSED: [Errno 111] Connection refused
[2/3] FAILURE CONNECTION_REFUSED: [Errno 111] Connection refused
[3/3] FAILURE CONNECTION_REFUSED: [Errno 111] Connection refused

Successes: 0
Failures: 3
Success rate: 0.00%
Avg successful connect time: N/A (no successful connections)
Failure breakdown:
  CONNECTION_REFUSED: 3
exit_code=1
```

CSV: [`samples/sample_server_stopped.csv`](../samples/sample_server_stopped.csv)

> Note: a stopped local server yields **connection refused**, not a timeout.
> The kernel sends RST because nothing is listening on the port.

### TC-03 — unused port

```text
[1/2] FAILURE CONNECTION_REFUSED: [Errno 111] Connection refused
[2/2] FAILURE CONNECTION_REFUSED: [Errno 111] Connection refused
exit_code=1
```

CSV: [`samples/sample_unused_port.csv`](../samples/sample_unused_port.csv)

### TC-04 — server stopped during the run

The tool ran 10 attempts at 1-second intervals; the server was killed after
about 3 seconds.

```text
[1/10] SUCCESS 0.200 ms (127.0.0.1)
[2/10] SUCCESS 0.129 ms (127.0.0.1)
[3/10] SUCCESS 0.097 ms (127.0.0.1)
[4/10] FAILURE CONNECTION_REFUSED: [Errno 111] Connection refused
...
[10/10] FAILURE CONNECTION_REFUSED: [Errno 111] Connection refused

Successes: 3
Failures: 7
Success rate: 30.00%
Avg successful connect time: 0.142 ms
exit_code=1
```

CSV: [`samples/sample_transition.csv`](../samples/sample_transition.csv)

The CSV shows the transition without any gaps: attempts 1–3 are `SUCCESS` with a
connect time, attempts 4–10 are `FAILURE` with an empty connect time.

### TC-05 — invalid arguments

```text
args='127.0.0.1 0'                                  exit_code=2
args='127.0.0.1 8000 -n 0'                          exit_code=2
args='127.0.0.1 abc'                                exit_code=2
args='127.0.0.1 8000 -o /tmp/does-not-exist/...'    exit_code=2
```

Example message:

```text
tcp_check.py: error: argument port: port must be 1-65535, got 0
```

### TC-06 — timeout

Target: `192.0.2.1:81` (`TEST-NET-1`, RFC 5737 — normally routed nowhere),
`--timeout 1`.

```text
[1/2] FAILURE TIMEOUT: timed out
[2/2] FAILURE TIMEOUT: timed out
Failure breakdown:
  TIMEOUT: 2
exit_code=1
```

CSV: [`samples/sample_timeout.csv`](../samples/sample_timeout.csv)

No firewall rules or system settings were changed. The environment-dependent
test is also available as an opt-in unit test:

```bash
RUN_TIMEOUT_TEST=1 python3 -m unittest tests.test_tcp_check.TestCheckOnce -v
```

### TC-07 — DNS failure

Target: `does-not-exist.invalid:80` (RFC 6761 reserves `.invalid`).

```text
[1/2] FAILURE DNS_ERROR: [Errno -2] Name or service not known (errno -2)
[2/2] FAILURE DNS_ERROR: [Errno -2] Name or service not known (errno -2)
exit_code=1
```

CSV: [`samples/sample_dns_error.csv`](../samples/sample_dns_error.csv)

The `resolved_address` column is empty, as intended.

### TC-08 — Ctrl+C

Sent `SIGINT` after ~1.2 s during a 5-attempt run with a 2 s interval:

```text
[1/5] FAILURE CONNECTION_REFUSED: [Errno 111] Connection refused
Ctrl+C received - stopping after completed attempts.

Attempts completed: 1/5
Run interrupted by Ctrl+C - partial results were saved.
tool exit code under SIGINT: 130
CSV rows (including header): 2
```

Also covered deterministically by the unit test
`test_ctrl_c_preserves_completed_rows` (mocked interrupt on attempt 2; asserts
1 CSV row and exit `130`).

### TC-09 — automated tests

```text
$ RUN_TIMEOUT_TEST=1 python3 -m unittest discover -s tests
----------------------------------------------------------------------
Ran 22 tests in 0.571s

OK
```

Coverage includes successful TCP connects, refused ports, DNS failures, all
error classifications, summary math including `N/A`, CSV mapping, exit codes
`0/1/2/130`, and interrupted-run preservation.

## Not tested (explicitly)

| Area | Why | How to cover it |
|---|---|---|
| Firewall `DROP` rule | Would require `sudo` and firewall changes | Manual `iptables` steps in the README |
| IPv6-only targets | Test environment used IPv4 loopback | Use `::1` and run against an IPv6-only listener |
| Real WAN / high-latency links | Not available in this environment | Run against a remote host from another region |
| Application-level health (HTTP 5xx) | Tool is intentionally L4-only | Add the HTTP exercise from the README |
| Concurrent target fan-out | Tool is sequential by design | Add the `ThreadPoolExecutor` exercise |
| Non-Linux platforms | Only Ubuntu was available | Run the CI matrix on macOS/Windows |
| Sustained load / long soak | Out of scope for this tool | Extend attempts and monitor resource use |

## Artifacts

| File | Scenario |
|---|---|
| [`samples/sample_success.csv`](../samples/sample_success.csv) | TC-01 |
| [`samples/sample_server_stopped.csv`](../samples/sample_server_stopped.csv) | TC-02 |
| [`samples/sample_unused_port.csv`](../samples/sample_unused_port.csv) | TC-03 |
| [`samples/sample_transition.csv`](../samples/sample_transition.csv) | TC-04 |
| [`samples/sample_timeout.csv`](../samples/sample_timeout.csv) | TC-06 |
| [`samples/sample_dns_error.csv`](../samples/sample_dns_error.csv) | TC-07 |

Reproduce TC-01 through TC-05 with:

```bash
./scripts/run_scenarios.sh
```
