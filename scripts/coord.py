#!/usr/bin/env python3
"""The persistent coordinator's Orca calls, so its allowlist needs one rule and no redirects.

  coord.py wait --run R --out PATH        # heartbeat, then the blocking check; stdout -> PATH
  coord.py scan --run R [--limit 100]     # inbox -> pending rows as JSON; window short: notice, exit 5
  coord.py advance --run R [--limit 100]  # inbox -> state.py scan advance
  coord.py seed --run R [--limit 100]     # inbox -> state.py scan seed

A non-zero Orca exit passes through with Orca's output. state.py exit codes pass
through too: 3 bad/missing file or refused, 5 scan window too short.
"""
import argparse, os, subprocess, sys

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
    state.write_heartbeat(os.environ.get("ORCA_TERMINAL_HANDLE", ""))
    out = orca(wait_argv(a.run))
    with open(a.out, "w") as f:
        f.write(out)


def cmd_scan(a):
    code = state_scan("pending", a.run, orca(inbox_argv(a.run, a.limit)), a.limit)
    if code == 5:
        state.notice_add("scan", f"inbox window short: {a.limit} rows all above the floor; raise --limit")
    sys.exit(code)


def cmd_advance(a):
    sys.exit(state_scan("advance", a.run, orca(inbox_argv(a.run, a.limit)), a.limit))


def cmd_seed(a):
    sys.exit(state_scan("seed", a.run, orca(inbox_argv(a.run, a.limit))))


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("wait"); w.add_argument("--run", required=True); w.add_argument("--out", required=True)
    w.set_defaults(fn=cmd_wait)
    for name, fn in (("scan", cmd_scan), ("advance", cmd_advance), ("seed", cmd_seed)):
        s = sub.add_parser(name); s.add_argument("--run", required=True)
        s.add_argument("--limit", type=int, default=100); s.set_defaults(fn=fn)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
