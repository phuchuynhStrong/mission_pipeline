#!/usr/bin/env python3
"""The persistent coordinator's Orca calls, so its allowlist needs one rule and no redirects.

  coord.py wait --run R --out PATH [--error-backoff 60]
                                          # heartbeat, then the blocking check; stdout -> PATH
                                          # Orca error (not consumer_fenced): sleep, then exit non-zero
  coord.py scan --run R [--limit 100]     # inbox -> pending rows as JSON; window short: exit 5
  coord.py advance --run R [--limit 100]  # inbox -> state.py scan advance
  coord.py seed --run R [--limit 100]     # inbox -> state.py scan seed

A non-zero Orca exit passes through with Orca's output. state.py exit codes pass
through too: 3 bad/missing file or refused, 5 scan window too short.
"""
import argparse, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # python3 -I drops the script folder
import state  # noqa: E402

STATE = os.path.join(HERE, "state.py")


def inbox_argv(run: str, limit: int) -> list:
    return ["orca", "orchestration", "inbox", "--terminal", f"run:{run}", "--limit", str(limit), "--full", "--json"]


def wait_argv(run: str) -> list:
    return ["orca", "orchestration", "check", "--run", run, "--wait", "--types",
            "worker_done,escalation,question", "--timeout-ms", "900000", "--full", "--json"]


def orca(argv):
    """Run Orca; on a non-zero exit print its output and exit with its code."""
    r = subprocess.run(argv, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stdout.write(r.stdout)
        sys.stderr.write(r.stderr)
        sys.exit(r.returncode)
    return r.stdout


def state_scan(action, run, stdin, limit=None):
    argv = [sys.executable, "-I", STATE, "scan", action, "--run", run]
    if limit is not None:
        argv += ["--limit", str(limit)]
    r = subprocess.run(argv, input=stdin, capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    return r.returncode


def cmd_wait(a):
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    state.write_heartbeat(os.environ.get("ORCA_TERMINAL_HANDLE", ""))
    r = subprocess.run(wait_argv(a.run), capture_output=True, text=True)
    if r.returncode != 0:
        sys.stdout.write(r.stdout)
        sys.stderr.write(r.stderr)
        if "consumer_fenced" not in r.stdout + r.stderr:
            sys.stdout.flush(); sys.stderr.flush()
            time.sleep(a.error_backoff)  # no hot loop when Orca is down
        sys.exit(r.returncode)
    with open(a.out, "w") as f:
        f.write(r.stdout)


def cmd_scan(a):
    # No notice here: the caller retries with --limit 500 and writes the notice only if that fails too.
    sys.exit(state_scan("pending", a.run, orca(inbox_argv(a.run, a.limit)), a.limit))


def cmd_advance(a):
    sys.exit(state_scan("advance", a.run, orca(inbox_argv(a.run, a.limit)), a.limit))


def cmd_seed(a):
    sys.exit(state_scan("seed", a.run, orca(inbox_argv(a.run, a.limit))))


def parser():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("wait"); w.add_argument("--run", required=True); w.add_argument("--out", required=True)
    w.add_argument("--error-backoff", type=float, default=60)
    w.set_defaults(fn=cmd_wait)
    for name, fn in (("scan", cmd_scan), ("advance", cmd_advance), ("seed", cmd_seed)):
        s = sub.add_parser(name); s.add_argument("--run", required=True)
        s.add_argument("--limit", type=int, default=100); s.set_defaults(fn=fn)
    return p


def main():
    a = parser().parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
