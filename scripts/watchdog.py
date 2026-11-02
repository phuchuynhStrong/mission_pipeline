"""Coordinator watchdog. launchd runs `watchdog.py run --workspace <ws>` every minute.

It relaunches the coordinator Claude session when its Orca terminal is gone, and only
writes a board notice when the terminal is alive but not working. It never types into
any terminal.

Usage:
  watchdog.py run --workspace <ws>
  watchdog.py resume
  watchdog.py plist --workspace <ws> [--python /usr/bin/python3]
"""
import argparse, json, os, plistlib, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import state  # noqa: E402

WATCHDOG = os.path.join(state.ROOT, "watchdog.json")
LABEL = "com.mission-pipeline.coordinator-watchdog"
ORCA_BIN = "/Applications/Orca.app/Contents/Resources/bin"
MIN = 60_000
LOCK_MS = 10 * MIN
FAIL_CHECK_MS = 5 * MIN
STALE_MS = 20 * MIN
PROMPTS = ("Do you want to proceed?", "Do you want to create")


def decide(obs: dict, now_ms: int) -> tuple:
    """Pure. Returns (action, reason); action is ok | launch | notice | locked | paused."""
    if obs["paused"]:
        return "paused", "paused after failed launches"
    if obs["live_handles"] is None:
        return "notice", "orca not answering"
    saved = obs["saved_terminal"]
    if not saved or saved not in obs["live_handles"]:
        last = obs["last_launch_ms"]
        if last is not None and now_ms - last < LOCK_MS:
            return "locked", "launched less than 10 min ago"
        return "launch", "terminal gone"
    if obs["bound_run"] != obs["shared_run"]:
        return "notice", "fenced"
    if any(p in (obs["screen"] or "") for p in PROMPTS):
        return "notice", "permission prompt"
    hb = obs["heartbeat_ms"]
    if hb is None or now_ms - hb > STALE_MS:
        return "notice", "not waiting"
    return "ok", ""


def count_failures(wd: dict, heartbeat_ms, now_ms: int) -> None:
    """Update failures/paused/last_launch_ms in wd after a launch."""
    last = wd.get("last_launch_ms")
    if last is None:
        return
    if heartbeat_ms is not None and heartbeat_ms >= last:
        wd["failures"] = 0
        return
    if now_ms - last >= FAIL_CHECK_MS and wd.get("failure_counted_for") != last:
        wd["failures"] = wd.get("failures", 0) + 1
        wd["failure_counted_for"] = last  # count each launch once; keep last_launch_ms for the lock
        if wd["failures"] >= 2:
            wd["paused"] = True


def orca(*args):
    """Run orca; return parsed JSON or None on any failure."""
    try:
        r = subprocess.run(["orca", *args], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None


def read_file_json(path):
    """(data, ok). Missing file → (None, True); bad JSON → (None, False)."""
    if not os.path.exists(path):
        return None, True
    try:
        with open(path) as f:
            return json.load(f), True
    except (OSError, ValueError):
        return None, False


def load_wd():
    data, ok = read_file_json(WATCHDOG)
    wd = {"last_launch_ms": None, "failures": 0, "paused": False, "last_notice": "",
          "failure_counted_for": None}
    if ok and isinstance(data, dict):
        wd.update(data)
    return wd


def notice(wd, reason):
    """Write a notice only when the reason differs from the last one stored."""
    if wd.get("last_notice") == reason:
        return
    state.notice_add("watchdog", f"coordinator: {reason}")
    wd["last_notice"] = reason


def gather(wd):
    """Returns (obs, error). error is a reason string when a root file is corrupt."""
    coord, ok = read_file_json(state.COORD)
    if not ok:
        return None, f"bad file {state.COORD}"
    hb, ok = read_file_json(state.HEARTBEAT)
    if not ok:
        hb = None
    coord = coord or {}
    saved = coord.get("terminal")
    shared = coord.get("run_id") or ""
    listed = orca("terminal", "list", "--limit", "1000", "--json")
    live = None
    try:
        live = {t["handle"] for t in listed["result"]["terminals"]}
        if listed["result"].get("truncated"):
            live = None  # partial list: the saved terminal may be past the cut, so unknown
    except (TypeError, KeyError, AttributeError):
        live = None
    bound, screen = None, ""
    if live is not None and saved in live:
        rc = orca("orchestration", "run-current", "--from", saved, "--json")
        try:
            bound = rc["result"]["runId"]
        except (TypeError, KeyError):
            bound = shared  # call failed: fence unknown, skip the check
        rd = orca("terminal", "read", "--terminal", saved, "--screen", "--json")
        try:
            screen = "\n".join(rd["result"]["terminal"]["tail"])
        except (TypeError, KeyError):
            screen = ""
    hb_ms = hb.get("at") if isinstance(hb, dict) and isinstance(hb.get("at"), int) else None
    return {"saved_terminal": saved, "live_handles": live, "bound_run": bound,
            "shared_run": shared, "screen": screen, "heartbeat_ms": hb_ms,
            "last_launch_ms": wd["last_launch_ms"], "failures": wd["failures"],
            "paused": wd["paused"]}, None


def find_terminal(data):
    """First string value starting with term_ anywhere in a launch receipt, or None."""
    if isinstance(data, str):
        return data if data.startswith("term_") else None
    items = data.values() if isinstance(data, dict) else data if isinstance(data, list) else []
    for v in items:
        found = find_terminal(v)
        if found:
            return found
    return None


def cmd_run(a):
    wd = load_wd()
    try:
        r = subprocess.run(["orca", "status", "--json"], capture_output=True, text=True, timeout=60)
        up = r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        up = False
    if not up:
        orca("open", "--json")
    now_ms = state.epoch_ms()
    obs, err = gather(wd)
    if err:
        notice(wd, err)
        state.write_json(WATCHDOG, wd)
        return 0
    was_paused = wd["paused"]
    count_failures(wd, obs["heartbeat_ms"], now_ms)
    if wd["paused"] and not was_paused:
        notice(wd, "paused after 2 failed launches; run watchdog.py resume")
    obs.update(last_launch_ms=wd["last_launch_ms"], failures=wd["failures"], paused=wd["paused"])
    action, reason = decide(obs, now_ms)
    if action == "launch":
        receipt = orca("agent", "launch", "--agent", "claude", "--surface", "terminal",
                       "--worktree", f"path:{a.workspace}", "--prompt", "/pipeline", "--json")
        wd["last_launch_ms"] = now_ms
        term = find_terminal(receipt)
        if term:
            coord, ok = read_file_json(state.COORD)
            if ok and isinstance(coord, dict) and isinstance(coord.get("run_id"), str) and coord["run_id"]:
                state.write_json(state.COORD, {**coord, "terminal": term})
    elif action == "notice":
        notice(wd, reason)
    elif action == "ok":
        wd["last_notice"] = ""
    state.write_json(WATCHDOG, wd)
    print(f"{action} {reason}".strip())
    return 0


def cmd_resume(a):
    wd = load_wd()
    wd["paused"] = False
    wd["failures"] = 0
    state.write_json(WATCHDOG, wd)
    return 0


def cmd_plist(a):
    path = os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
    plist = {
        "Label": LABEL,
        "ProgramArguments": [a.python, "-I", os.path.abspath(__file__), "run", "--workspace", a.workspace],
        "StartInterval": 60,
        "RunAtLoad": True,
        "StandardErrorPath": os.path.join(state.ROOT, "watchdog.log"),
        "EnvironmentVariables": {"PATH": f"{ORCA_BIN}:{path}"},
    }
    sys.stdout.write(plistlib.dumps(plist).decode())
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="watchdog.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--workspace", required=True)
    sub.add_parser("resume")
    pl = sub.add_parser("plist")
    pl.add_argument("--workspace", required=True)
    pl.add_argument("--python", default="/usr/bin/python3")
    a = p.parse_args(argv)
    return {"run": cmd_run, "resume": cmd_resume, "plist": cmd_plist}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
