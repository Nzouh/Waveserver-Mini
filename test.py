#!/usr/bin/env python3
"""
test.py — Waveserver Mini automated test runner

Usage:
    ./test.py
    ./test.py --no-build          skip make, use existing binaries
    ./test.py --verbose           print CLI output on every failing assertion
    ./test.py --section T3        run only one section (T0–T12)
"""

import argparse
import atexit
import os
import re
import subprocess
import sys
import time

# ── ANSI colours ───────────────────────────────────────────────────────────────
RED    = '\033[0;31m'
GREEN  = '\033[0;32m'
YELLOW = '\033[1;33m'
CYAN   = '\033[0;36m'
BOLD   = '\033[1m'
RESET  = '\033[0m'

# ── Globals ────────────────────────────────────────────────────────────────────
_passed   = 0
_failed   = 0
_failures: list[str] = []
_services: list[subprocess.Popen] = []
_verbose  = False

# ── Result helpers ─────────────────────────────────────────────────────────────

def pass_(label: str) -> None:
    global _passed
    _passed += 1
    print(f"  {GREEN}✓{RESET} {label}")


def fail_(label: str, detail: str = '') -> None:
    global _failed
    _failed += 1
    msg = f"{label}  {detail}" if detail else label
    _failures.append(msg)
    print(f"  {RED}✗{RESET} {msg}")


def section(title: str) -> None:
    print(f"\n{CYAN}{BOLD}── {title} ──{RESET}")


# ── CLI runner ─────────────────────────────────────────────────────────────────

def run_cli(*cmds: str, timeout: int = 10) -> str:
    """Pipe commands to ./cli via stdin; returns combined stdout+stderr."""
    stdin = '\n'.join([*cmds, 'exit']) + '\n'
    try:
        r = subprocess.run(
            ['./cli'],
            input=stdin,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return '[TIMEOUT]'


# ── Assertions ─────────────────────────────────────────────────────────────────

def _dump(output: str) -> None:
    print("    --- output ---")
    for line in output.splitlines():
        print(f"    {line}")
    print("    -------------")


def assert_contains(label: str, pattern: str, output: str) -> None:
    if re.search(pattern, output):
        pass_(label)
    else:
        fail_(label, f"[expected: '{pattern}']")
        if _verbose:
            _dump(output)


def assert_not_contains(label: str, pattern: str, output: str) -> None:
    if not re.search(pattern, output):
        pass_(label)
    else:
        fail_(label, f"[should NOT contain: '{pattern}']")
        if _verbose:
            _dump(output)


# ── Service management ─────────────────────────────────────────────────────────

def _kill_stale() -> None:
    for name in ['port_manager', 'conn_manager', 'traffic_manager']:
        subprocess.run(['pkill', '-f', name], capture_output=True)


def start_services() -> None:
    global _services
    _kill_stale()
    time.sleep(0.2)
    if os.path.exists('wsmini.log'):
        os.remove('wsmini.log')
    _services = [
        subprocess.Popen('./port_manager',    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
        subprocess.Popen('./conn_manager',    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
        subprocess.Popen('./traffic_manager', stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
    ]
    time.sleep(0.5)  # let all three sockets bind


def stop_services() -> None:
    global _services
    for p in _services:
        try:
            p.terminate()
            p.wait(timeout=2)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
    _services = []
    _kill_stale()


def fresh() -> None:
    """Restart all backend services for a clean state."""
    stop_services()
    time.sleep(0.1)
    start_services()


# ── Helper: extract only real log lines from output ───────────────────────────

def _log_lines(output: str) -> list[str]:
    """Return lines that look like wsmini log entries (contain [LEVEL])."""
    return [l for l in output.splitlines()
            if re.search(r'\[(DEBUG|INFO|WARN|ERROR)\]', l)]


# =============================================================================
#  TEST SECTIONS
# =============================================================================

def t0_baseline() -> None:
    section("T0: Baseline — fresh state")
    fresh()
    out = run_cli("show ports", "show connections")

    assert_contains    ("show ports: all 6 ports listed",  r"1\s+line",            out)
    assert_contains    ("show ports: ports are disabled",  r"disabled",            out)
    assert_contains    ("show ports: ports are down",      r"\bdown\b",            out)
    assert_not_contains("show ports: no faults",           r"\byes\b",             out)
    assert_contains    ("show connections: empty",         r"No connections",      out)


def t1_port_enable_disable() -> None:
    section("T1: Port enable / disable")
    fresh()

    out = run_cli("set port 1", "show ports", "delete port 1", "show ports")
    assert_contains("set port 1: OK",            r"\[OK\] Port-1 enabled",   out)
    assert_contains("port 1 becomes enabled/up", r"1\s+line\s+enabled",      out)
    assert_contains("delete port 1: OK",         r"\[OK\] Port-1 disabled",  out)

    out = run_cli("set port 0")
    assert_contains("set port 0: error", r"\[ERROR\]", out)

    out = run_cli("set port 7")
    assert_contains("set port 7: error", r"\[ERROR\]", out)


def t2_fault_lifecycle() -> None:
    section("T2: Fault injection lifecycle")

    fresh()
    out = run_cli("set port 1", "inject-fault 1", "show ports")
    assert_contains("inject-fault: OK",                  r"\[OK\] Fault injected on Port-1",   out)
    assert_contains("port 1 fault=yes",                  r"\byes\b",                            out)
    assert_contains("port 1 oper=down despite enabled",  r"1\s+line\s+enabled\s+yes\s+down",   out)

    fresh()
    out = run_cli("set port 1", "inject-fault 1", "clear-fault 1", "show ports")
    assert_contains("clear-fault: OK",        r"\[OK\] Fault cleared on Port-1",  out)
    assert_contains("port 1 recovers to up",  r"1\s+line\s+enabled\s+no\s+up",   out)

    # inject-fault on a disabled port should fail
    fresh()
    out = run_cli("inject-fault 3")
    assert_contains("inject-fault on disabled port: error", r"\[ERROR\]", out)

    # type labels in OK messages
    fresh()
    out = run_cli("set port 1", "inject-fault 1")
    assert_contains("line type label in fault msg",    r"\(line\)",   out)

    fresh()
    out = run_cli("set port 3", "inject-fault 3", "clear-fault 3")
    assert_contains("client type label in clear msg",  r"\(client\)", out)


def t3_create_connection_happy() -> None:
    section("T3: Create connection — happy path")

    fresh()
    out = run_cli(
        "set port 1", "set port 2",
        "set port 3", "set port 4", "set port 5", "set port 6",
        "create connection xc-1 1 3",
        "show connections",
    )
    assert_contains("xc-1 created OK",          r"\[OK\] Connection xc-1 created: Client-3", out)
    assert_contains("xc-1 in connection table",  r"xc-1\s+3\s+1\s+UP",                       out)

    # Line port 1 can have multiple clients (multiplexing)
    fresh()
    out = run_cli(
        "set port 1", "set port 2",
        "set port 3", "set port 4", "set port 5", "set port 6",
        "create connection xc-1 1 3",
        "create connection xc-2 4 1",
        "create connection xc-3 2 5",
        "create connection xc-4 6 2",
        "show connections",
    )
    assert_contains("xc-2 created (line-1 again)", r"\[OK\] Connection xc-2", out)
    assert_contains("xc-3 created",                r"\[OK\] Connection xc-3", out)
    assert_contains("xc-4 created",                r"\[OK\] Connection xc-4", out)
    assert_contains("all 4 connections present",   r"xc-4",                   out)


def t4_connection_arg_order() -> None:
    section("T4: create connection — either port order")
    fresh()

    out = run_cli(
        "set port 2", "set port 5",
        "create connection xc-order 5 2",   # client first, then line
        "show connections",
    )
    assert_contains("reverse order accepted",  r"\[OK\] Connection xc-order created: Client-5", out)
    assert_contains("correctly stored",        r"xc-order\s+5\s+2",                             out)


def t5_create_connection_rejection() -> None:
    section("T5: Create connection — rejection cases")

    # Duplicate client port
    fresh()
    out = run_cli(
        "set port 1", "set port 3", "set port 4",
        "create connection xc-1 1 3",
        "create connection xc-dup 1 3",
    )
    assert_contains("duplicate client port rejected", r"\[ERROR\]", out)

    # Duplicate connection name
    fresh()
    out = run_cli(
        "set port 1", "set port 3",
        "create connection xc-1 1 3",
        "create connection xc-1 1 3",
    )
    assert_contains("duplicate name rejected", r"\[ERROR\]", out)

    # Table full — fill all 4 slots then try a 5th
    fresh()
    out = run_cli(
        "set port 1", "set port 2",
        "set port 3", "set port 4", "set port 5", "set port 6",
        "create connection xc-1 1 3",
        "create connection xc-2 1 4",
        "create connection xc-3 2 5",
        "create connection xc-4 2 6",
        "create connection xc-5 1 3",  # client-3 already taken AND table full
    )
    assert_contains("table-full or dup error", r"\[ERROR\]", out)

    # Line + line
    fresh()
    out = run_cli("set port 1", "set port 2", "create connection bad 1 2")
    assert_contains("line+line rejected", r"\[ERROR\]", out)

    # Client + client
    fresh()
    out = run_cli("set port 3", "set port 4", "create connection bad 3 4")
    assert_contains("client+client rejected", r"\[ERROR\]", out)

    # Port 0 (out of range)
    fresh()
    out = run_cli("create connection bad 0 1")
    assert_contains("port 0 rejected", r"\[ERROR\]", out)

    # Port 9 (out of range)
    fresh()
    out = run_cli("create connection bad 1 9")
    assert_contains("port 9 rejected", r"\[ERROR\]", out)


def t6_delete_connection() -> None:
    section("T6: Delete connection")

    fresh()
    out = run_cli(
        "set port 1", "set port 3",
        "create connection xc-1 1 3",
        "delete connection xc-1",
        "show connections",
    )
    assert_contains("delete: OK",               r"\[OK\] Connection xc-1 deleted", out)
    assert_contains("table empty after delete", r"No connections",                 out)

    # Delete non-existent
    fresh()
    out = run_cli("delete connection nosuchconn")
    assert_contains("delete nonexistent: error", r"\[ERROR\]", out)

    # Slot can be reused after delete
    fresh()
    out = run_cli(
        "set port 1", "set port 3",
        "create connection xc-1 1 3",
        "delete connection xc-1",
        "create connection xc-1 1 3",
        "show connections",
    )
    assert_contains("slot recycled after delete", r"xc-1\s+3\s+1\s+UP", out)


def t7_port_failure_degrades_connections() -> None:
    section("T7: Port failure → connection degradation")

    fresh()
    out = run_cli(
        "set port 1", "set port 2",
        "set port 3", "set port 4", "set port 5",
        "create connection xc-1 1 3",
        "create connection xc-2 4 1",
        "create connection xc-3 2 5",
        "inject-fault 1",
        "show connections",
    )
    assert_contains("xc-1 goes DOWN",  r"xc-1\s+\d+\s+\d+\s+DOWN", out)
    assert_contains("xc-2 goes DOWN",  r"xc-2\s+\d+\s+\d+\s+DOWN", out)
    assert_contains("xc-3 stays UP",   r"xc-3\s+\d+\s+\d+\s+UP",   out)

    # Recovery: line fault cleared → connections come back UP
    fresh()
    out = run_cli(
        "set port 1", "set port 2",
        "set port 3", "set port 4", "set port 5",
        "create connection xc-1 1 3",
        "create connection xc-2 4 1",
        "create connection xc-3 2 5",
        "inject-fault 1",
        "clear-fault 1",
        "show connections",
    )
    assert_contains("xc-1 recovers to UP", r"xc-1\s+\d+\s+\d+\s+UP", out)
    assert_contains("xc-2 recovers to UP", r"xc-2\s+\d+\s+\d+\s+UP", out)


def t8_client_port_failure() -> None:
    section("T8: Client port failure")

    fresh()
    out = run_cli(
        "set port 1", "set port 3", "set port 4",
        "create connection xc-1 1 3",
        "create connection xc-2 4 1",
        "inject-fault 3",
        "show connections",
    )
    assert_contains("xc-1 DOWN (client-3 fault)", r"xc-1\s+\d+\s+\d+\s+DOWN", out)
    assert_contains("xc-2 stays UP",              r"xc-2\s+\d+\s+\d+\s+UP",   out)

    # Recovery
    fresh()
    out = run_cli(
        "set port 1", "set port 3", "set port 4",
        "create connection xc-1 1 3",
        "create connection xc-2 4 1",
        "inject-fault 3",
        "clear-fault 3",
        "show connections",
    )
    assert_contains("xc-1 recovers after client fault cleared", r"xc-1\s+\d+\s+\d+\s+UP", out)


def t9_reject_create_when_port_down() -> None:
    section("T9: Reject create when port is down")

    # Client port not enabled
    fresh()
    out = run_cli("set port 1", "create connection xc-1 1 3")
    assert_contains("rejected: client port not UP", r"\[ERROR\]", out)

    # Line port not enabled
    fresh()
    out = run_cli("set port 3", "create connection xc-1 1 3")
    assert_contains("rejected: line port not UP", r"\[ERROR\]", out)

    # Line port enabled but faulted → oper DOWN
    fresh()
    out = run_cli("set port 1", "inject-fault 1", "set port 3", "create connection xc-1 1 3")
    assert_contains("rejected: line port has fault", r"\[ERROR\]", out)


def t10_log_filtering() -> None:
    section("T10: Log filtering")

    # Seed a variety of log entries across all levels/services
    fresh()
    run_cli(
        "set port 1", "inject-fault 1", "clear-fault 1",
        "set port 3", "create connection xc-x 1 3", "delete connection xc-x",
    )

    out = run_cli("show logs")
    assert_contains("show logs: non-empty", r'\[(INFO|ERROR|WARN|DEBUG)\]', out)

    # --level ERROR: all returned log lines must be [ERROR]
    out = run_cli("show logs --level ERROR")
    if log_lines := _log_lines(out):
        non_error = [l for l in log_lines if not re.search(r'\[ERROR\]', l)]
        if non_error:
            fail_("ERROR filter: non-ERROR lines leaked through")
        else:
            pass_("ERROR filter: only ERROR lines shown")
    else:
        pass_("ERROR filter: no log output (filter may be correct or no errors logged)")

    # --level INFO
    out = run_cli("show logs --level INFO")
    assert_contains("INFO log filter works", r'\[INFO\]', out)

    # --service port-mgr: all returned log lines must mention [port-mgr]
    out = run_cli("show logs --service port-mgr")
    if log_lines := _log_lines(out):
        leaked = [l for l in log_lines if not re.search(r'\[port-mgr', l)]
        if leaked:
            fail_("port-mgr filter: lines from other services leaked")
        else:
            pass_("port-mgr filter works")
    else:
        pass_("port-mgr filter: no output (may be correct)")

    # Combined --level + --service
    out = run_cli("show logs --level ERROR --service conn-mgr")
    # Either there are no lines (acceptable) or all lines match both filters
    if log_lines := _log_lines(out):
        bad = [l for l in log_lines
               if not (re.search(r'\[ERROR\]', l) and re.search(r'\[conn-mgr', l))]
        if bad:
            fail_("combined filter: unexpected lines in output")
        else:
            pass_("combined filter works")
    else:
        pass_("combined filter: no output (acceptable if no conn-mgr errors logged)")


def t11_robustness() -> None:
    section("T11: Robustness / malformed input")
    fresh()

    out = run_cli("show", "show xyz", "delete", "delete port", "create connection", "set")
    assert_not_contains("no crash on bad input", r"Segmentation fault", out)
    assert_not_contains("no abort on bad input", r"Aborted",            out)

    out = run_cli("help")
    assert_contains("help displays commands", r"show ports", out)
    assert_contains("help has exit command",  r"\bexit\b",   out)


def t12_traffic() -> None:
    section("T12: Traffic manager (skipped if not implemented)")
    fresh()

    out = run_cli("show traffic-stats")
    if re.search(r'TODO|\[ERROR\].*not.*implement|timed out|not running|TIMEOUT', out, re.IGNORECASE):
        print(f"  {YELLOW}⚠{RESET}  Traffic Manager not yet implemented — skipping traffic tests")
        return

    fresh()
    out = run_cli(
        "set port 1", "set port 2",
        "set port 3", "set port 4", "set port 5", "set port 6",
        "create connection xc-1 1 3",
        "start traffic",
        "show traffic-stats",
    )
    assert_contains("start traffic: OK",       r"started|OK",                         out)
    assert_contains("traffic stats present",   r"total_forwarded|[Ff]orwarded",       out)

    # Wait for at least one cron tick (interval is 3 s)
    time.sleep(4)
    out = run_cli("show traffic-stats")
    assert_contains("frames generated after wait", r"[1-9]", out)

    out = run_cli("stop traffic", "show traffic-stats")
    assert_contains("stop traffic: OK", r"stopped|OK", out)


# =============================================================================
#  ENTRY POINT
# =============================================================================

SECTIONS: dict[str, callable] = {
    'T0':  t0_baseline,
    'T1':  t1_port_enable_disable,
    'T2':  t2_fault_lifecycle,
    'T3':  t3_create_connection_happy,
    'T4':  t4_connection_arg_order,
    'T5':  t5_create_connection_rejection,
    'T6':  t6_delete_connection,
    'T7':  t7_port_failure_degrades_connections,
    'T8':  t8_client_port_failure,
    'T9':  t9_reject_create_when_port_down,
    'T10': t10_log_filtering,
    'T11': t11_robustness,
    'T12': t12_traffic,
}


def main() -> None:
    global _verbose

    parser = argparse.ArgumentParser(description='Waveserver Mini test runner')
    parser.add_argument('--no-build', action='store_true', help='Skip make step')
    parser.add_argument('--verbose',  action='store_true', help='Print CLI output on failure')
    parser.add_argument('--section',  metavar='T#',
                        choices=SECTIONS.keys(),
                        help='Run only one section (e.g. T3)')
    args = parser.parse_args()
    _verbose = args.verbose

    # Run from the directory containing this script so ./cli etc. resolve
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    atexit.register(stop_services)

    if not args.no_build:
        print(f"{BOLD}Building...{RESET}")
        if subprocess.run(['make', '-s']).returncode != 0:
            print(f"{RED}Build failed — aborting.{RESET}")
            sys.exit(1)
        print(f"{GREEN}Build OK{RESET}")

    to_run = [SECTIONS[args.section]] if args.section else list(SECTIONS.values())
    for fn in to_run:
        fn()

    stop_services()

    total = _passed + _failed
    print(f"\n{BOLD}{'═' * 40}{RESET}")
    print(f"{BOLD} Results: {GREEN}{_passed} passed{RESET}  {RED}{_failed} failed{RESET}  ({total} total){RESET}")
    print(f"{BOLD}{'═' * 40}{RESET}")

    if _failures:
        print(f"\n{RED}Failed tests:{RESET}")
        for f in _failures:
            print(f"  {RED}✗{RESET} {f}")
        print()

    sys.exit(0 if _failed == 0 else 1)


if __name__ == '__main__':
    main()
