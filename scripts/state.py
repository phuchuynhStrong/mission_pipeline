#!/usr/bin/env python3
"""Mission state for the pipeline skill. One JSON file per mission.

  state.py new  <repo-slug> <id> --run-id R --ticket WBS-1 --title "..." --repo /abs --base-branch B
  state.py set  <repo-slug> <id> stage=spec stages.spec.status=active note="..." events+="text"
  state.py abort <repo-slug> <id> --reason "..."   # stage=aborted, open stages -> failed
  state.py done  <repo-slug> <id> --reason "..."   # stage=done (PR merged / user said so)
  state.py show <repo-slug> <id>
  state.py path <repo-slug> <id>
  state.py list [repo-slug] [--all]        # done/aborted missions hidden unless --all
  state.py run [--set <run_id>]            # the coordinator's saved Run (coordinator.json)
  state.py owner <dispatch_id>             # -> "<repo-slug> <id> live|settled"
  state.py handled start <msg> --seq N --type T [--from F] [--kind outside|mission] [--summary S]
  state.py handled answer <msg> [--summary S] | get <msg> | open
  state.py scan seed --run R | floor | pending --run R --limit N | advance --run R --limit N   # stdin: inbox --json

`run` exits 3 when coordinator.json is corrupt or has no run_id. `owner` exits 3 when
no open mission lists the Dispatch, 4 when two do; any other non-zero exit is a failure.

Dotted keys walk nested dicts. A value is parsed as JSON when it parses,
else kept as a string. `key+=value` appends to a list; `dispatches+=` and
`settled+=` always append the raw string.

`attention` is the board's switch button: set `attention.terminal=<handle>
attention.reason="<one line>"` when a mission waits on the user; `attention=null` clears it.
"""
import json, os, sys, argparse, datetime, tempfile

ROOT = os.path.join(os.path.expanduser("~"), ".claude", "pipeline")
STAGES = ["read", "spec", "plan", "worktree", "build", "review", "pr"]
TERMINAL = ["done", "aborted"]  # stage values the board treats as closed; "ready" (PR open, waiting merge) is still open
COORD = os.path.join(ROOT, "coordinator.json")  # the coordinator's saved Run, shared by every mission
RAW_LISTS = ("dispatches", "settled")  # Orca ids: append as given, never parse_value


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def path_of(slug, mid):
    return os.path.join(ROOT, slug, f"{mid}.json")


def load(slug, mid):
    with open(path_of(slug, mid)) as f:
        return json.load(f)


def save(slug, mid, data):
    p = path_of(slug, mid)
    data["updated"] = now()
    write_json(p, data)


def write_json(p, data):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(p), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, p)


def write_text(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(p), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.replace(tmp, p)


def open_missions():
    """(slug, mission) for every mission not done/aborted; stray files are skipped."""
    if not os.path.isdir(ROOT):
        return
    for s in sorted(os.listdir(ROOT)):
        d = os.path.join(ROOT, s)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if name.endswith(".json"):
                with open(os.path.join(d, name)) as f:
                    m = json.load(f)
                if m.get("stage") not in TERMINAL:
                    yield s, m


def parse_value(raw):
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def walk(data, dotted, create=True):
    keys = dotted.split(".")
    node = data
    for k in keys[:-1]:
        if not isinstance(node.get(k), dict):
            if not create:
                raise KeyError(dotted)
            node[k] = {}  # missing or null (e.g. attention=null): start a fresh dict
        node = node[k]
    return node, keys[-1]


def cmd_new(a):
    data = {
        "id": a.id, "ticket": a.ticket or "", "title": a.title or "",
        "repo": a.repo or "", "repo_slug": a.slug, "run_id": a.run_id,
        "dispatches": [], "settled": [],
        "base_branch": a.base_branch or "", "created": now(), "updated": "",
        "stage": "read", "note": "created", "attention": None,
        "stages": {
            "read": {"status": "pending", "workers": [], "paths": []},
            "spec": {"status": "pending", "worker": "", "path": ""},
            "plan": {"status": "pending", "worker": "", "path": "", "tasks": 0, "parallel": False},
            "worktree": {"status": "pending", "path": "", "branch": ""},
            "build": {"status": "pending", "workers": [], "done": 0},
            "review": {"status": "pending", "worker": "", "verdict": "", "rounds": 0},
            "pr": {"status": "pending", "number": 0, "url": "", "greptile": "", "worker": ""},
        },
        "events": [{"at": now(), "text": "mission created"}],
    }
    if os.path.exists(path_of(a.slug, a.id)):
        sys.exit(f"exists: {path_of(a.slug, a.id)}")
    save(a.slug, a.id, data)
    print(path_of(a.slug, a.id))


def cmd_set(a):
    data = load(a.slug, a.id)
    for pair in a.pairs:
        if "+=" in pair:
            key, raw = pair.split("+=", 1)
            node, last = walk(data, key)
            node.setdefault(last, [])
            val = parse_value(raw)
            if key == "events":
                val = {"at": now(), "text": raw}
            elif key in RAW_LISTS:
                val = raw
            node[last].append(val)
        elif "=" in pair:
            key, raw = pair.split("=", 1)
            node, last = walk(data, key)
            node[last] = parse_value(raw)
        else:
            sys.exit(f"bad pair: {pair}")
    save(a.slug, a.id, data)
    print(f'{data["id"]} stage={data["stage"]} note={data["note"]}')


def cmd_abort(a):
    data = load(a.slug, a.id)
    if data["stage"] in TERMINAL:
        sys.exit(f'{data["id"]} already {data["stage"]}')
    for name in STAGES:
        st = data["stages"].get(name, {})
        if st.get("status") in ("active", "waiting_user"):
            st["status"] = "failed"
    data["stage"] = "aborted"
    data["note"] = f"ABORTED: {a.reason}" if a.reason else "ABORTED by user"
    data["events"].append({"at": now(), "text": data["note"]})
    save(a.slug, a.id, data)
    print(f'{data["id"]} stage={data["stage"]} note={data["note"]}')


def cmd_done(a):
    data = load(a.slug, a.id)
    if data["stage"] in TERMINAL:
        sys.exit(f'{data["id"]} already {data["stage"]}')
    data["stage"] = "done"
    data["note"] = f"DONE: {a.reason}" if a.reason else "DONE by user"
    data["events"].append({"at": now(), "text": data["note"]})
    save(a.slug, a.id, data)
    print(f'{data["id"]} stage={data["stage"]} note={data["note"]}')


def cmd_show(a):
    print(json.dumps(load(a.slug, a.id), indent=2))


def cmd_path(a):
    print(path_of(a.slug, a.id))


def read_coord():
    """Saved coordinator file, or None when missing. Exit 3 when it does not parse."""
    if not os.path.exists(COORD):
        return None
    try:
        with open(COORD) as f:
            return json.load(f)
    except (ValueError, OSError):
        print(f"bad coordinator file: {COORD}", file=sys.stderr)
        sys.exit(3)


def cmd_run(a):
    data = read_coord()
    if a.set_id is None and a.terminal is not None:
        rid = data.get("run_id") if isinstance(data, dict) else None
        if not isinstance(rid, str) or not rid:
            print(f"bad coordinator file (no run_id): {COORD}", file=sys.stderr)
            sys.exit(3)
        out = dict(data)
        out["terminal"] = a.terminal
        out["updated"] = now()
        write_json(COORD, out)
        print(rid)
        return
    if a.set_id is None:
        if data is None:
            print("")
            return
        rid = data.get("run_id") if isinstance(data, dict) else None
        if not isinstance(rid, str) or not rid:
            print(f"bad coordinator file (no run_id): {COORD}", file=sys.stderr)
            sys.exit(3)
        print(rid)
        return
    if not a.set_id:
        print("refused: empty run_id", file=sys.stderr)
        sys.exit(3)
    out = dict(data or {}) if isinstance(data, dict) or data is None else {}
    out["run_id"] = a.set_id
    out["created"] = out.get("created") or now()
    out["updated"] = now()
    if a.terminal is not None:
        out["terminal"] = a.terminal
    write_json(COORD, out)
    print(a.set_id)


HANDLED = os.path.join(ROOT, "handled.jsonl")  # one line per Orca message the coordinator starts/answers
SCAN = os.path.join(ROOT, "scan.json")  # inbox floor: every matching message with sequence <= floor is answered


def read_handled():
    """handled.jsonl entries in file order. Exit 3 on any line that does not parse."""
    if not os.path.exists(HANDLED):
        return []
    out = []
    try:
        with open(HANDLED) as f:
            for line in f:
                if line.strip():
                    e = json.loads(line)
                    if not isinstance(e, dict):
                        raise ValueError(line)
                    out.append(e)
    except (ValueError, OSError):
        print(f"bad handled file: {HANDLED}", file=sys.stderr)
        sys.exit(3)
    return out


def handled_map():
    """msg_id -> last entry for it."""
    return {e.get("msg_id"): e for e in read_handled()}


def handled_status(msg_id):
    e = handled_map().get(msg_id)
    return e.get("status", "none") if e else "none"


def append_handled(entry):
    os.makedirs(ROOT, exist_ok=True)
    with open(HANDLED, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _matching(rows, run_id):
    return [r for r in rows if r.get("to_handle") == f"run:{run_id}" and isinstance(r.get("sequence"), int)]


def pending_rows(rows, run_id, floor):
    done = handled_map()
    out = [r for r in _matching(rows, run_id) if r["sequence"] > floor
           and (done.get(r.get("id")) or {}).get("status") != "answered"]
    return sorted(out, key=lambda r: r["sequence"])


def next_floor(rows, run_id, floor):
    done = handled_map()
    out = floor
    for r in sorted(_matching(rows, run_id), key=lambda r: r["sequence"]):
        if r["sequence"] <= floor:
            continue
        if (done.get(r.get("id")) or {}).get("status") != "answered":
            break
        out = r["sequence"]
    return out


def window_short(rows, floor, limit):
    seqs = [r["sequence"] for r in rows if isinstance(r.get("sequence"), int)]
    return len(rows) >= limit and bool(seqs) and min(seqs) > floor


def cmd_handled(a):
    if a.action == "start":
        try:
            seq = int(a.seq)
        except (TypeError, ValueError):
            seq = 0
        if seq <= 0:
            print("refused: --seq must be an integer > 0", file=sys.stderr)
            sys.exit(3)
        if handled_status(a.msg) == "answered":  # answered is sticky; also refuses a corrupt file
            print(f"refused: {a.msg} already answered", file=sys.stderr)
            sys.exit(3)
        append_handled({"msg_id": a.msg, "seq": seq, "type": a.type, "from": a.from_ or "",
                        "kind": a.kind or "", "status": "started", "at": now(), "summary": a.summary or ""})
        print("started")
    elif a.action == "answer":
        start = next((e for e in read_handled() if e.get("msg_id") == a.msg and e.get("status") == "started"), None)
        if start is None:
            print(f"refused: no start line for {a.msg}", file=sys.stderr)
            sys.exit(3)
        append_handled({**start, "status": "answered", "at": now(), "summary": a.summary or start.get("summary", "")})
        print("answered")
    elif a.action == "get":
        print(handled_status(a.msg))
    else:
        for e in handled_map().values():
            if e.get("status") == "started":
                print(json.dumps(e))


def read_scan():
    """scan.json, or exit 3 when missing or corrupt."""
    if not os.path.exists(SCAN):
        print(f"not seeded: {SCAN}", file=sys.stderr)
        sys.exit(3)
    try:
        with open(SCAN) as f:
            data = json.load(f)
        if not isinstance(data.get("floor"), int):
            raise ValueError("floor")
        return data
    except (ValueError, OSError, AttributeError):
        print(f"bad scan file: {SCAN}", file=sys.stderr)
        sys.exit(3)


def read_inbox():
    """Rows from `orca orchestration inbox --json` on stdin. Exit 3 when it does not parse."""
    try:
        rows = json.loads(sys.stdin.read())["result"]["messages"]
        if not isinstance(rows, list):
            raise ValueError("messages")
        return rows
    except (ValueError, KeyError, TypeError):
        print("bad inbox json on stdin", file=sys.stderr)
        sys.exit(3)


def read_scan_for(run_id):
    """scan.json for this Run; exit 3 when it was seeded for another Run."""
    data = read_scan()
    if data.get("run_id") != run_id:
        print(f"refused: {SCAN} is for run {data.get('run_id')}, not {run_id}", file=sys.stderr)
        sys.exit(3)
    return data


def cmd_scan(a):
    if a.action == "seed":
        if os.path.exists(SCAN) and read_scan().get("run_id") == a.run:
            print(f"refused: already seeded: {SCAN}", file=sys.stderr)
            sys.exit(3)
        seqs = [r["sequence"] for r in _matching(read_inbox(), a.run)]
        floor = max(seqs) if seqs else 0
        write_json(SCAN, {"run_id": a.run, "floor": floor, "updated": now()})
        print(floor)
    elif a.action == "floor":
        print(read_scan()["floor"])
    elif a.action == "pending":
        floor = read_scan_for(a.run)["floor"]
        rows = read_inbox()
        print(json.dumps(pending_rows(rows, a.run, floor)))
        if window_short(rows, floor, a.limit):
            print(f"window short: {len(rows)} rows, all above floor {floor}", file=sys.stderr)
            sys.exit(5)
    else:
        data = read_scan_for(a.run)
        rows = read_inbox()
        if window_short(rows, data["floor"], a.limit):
            print(f"window short: {len(rows)} rows, all above floor {data['floor']}; floor kept", file=sys.stderr)
            sys.exit(5)
        floor = next_floor(rows, a.run, data["floor"])
        keep = [e for e in read_handled() if not (isinstance(e.get("seq"), int) and e["seq"] <= floor)]
        write_json(SCAN, {**data, "run_id": a.run, "floor": floor, "updated": now()})
        if os.path.exists(HANDLED):
            write_text(HANDLED, "".join(json.dumps(e) + "\n" for e in keep))
        print(floor)


def cmd_owner(a):
    hits = [
        f'{s} {m["id"]} {"settled" if a.dispatch in m.get("settled", []) else "live"}'
        for s, m in open_missions()
        if a.dispatch in m.get("dispatches", [])
    ]
    for h in hits:
        print(h)
    if not hits:
        sys.exit(3)
    if len(hits) > 1:
        sys.exit(4)


def cmd_list(a):
    slugs = [a.slug] if a.slug else sorted(
        s for s in os.listdir(ROOT) if os.path.isdir(os.path.join(ROOT, s))
    ) if os.path.isdir(ROOT) else []
    for s in slugs:
        d = os.path.join(ROOT, s)
        for name in sorted(os.listdir(d)):
            if name.endswith(".json"):
                with open(os.path.join(d, name)) as f:
                    m = json.load(f)
                if m.get("stage") in TERMINAL and not a.all:
                    continue
                print(f'{s}/{m["id"]}  stage={m["stage"]}  {m.get("note","")}')


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new"); n.add_argument("slug"); n.add_argument("id")
    n.add_argument("--ticket"); n.add_argument("--title"); n.add_argument("--repo"); n.add_argument("--base-branch")
    n.add_argument("--run-id", required=True)
    n.set_defaults(fn=cmd_new)
    s = sub.add_parser("set"); s.add_argument("slug"); s.add_argument("id"); s.add_argument("pairs", nargs="+")
    s.set_defaults(fn=cmd_set)
    ab = sub.add_parser("abort"); ab.add_argument("slug"); ab.add_argument("id"); ab.add_argument("--reason")
    ab.set_defaults(fn=cmd_abort)
    dn = sub.add_parser("done"); dn.add_argument("slug"); dn.add_argument("id"); dn.add_argument("--reason")
    dn.set_defaults(fn=cmd_done)
    for name, fn in (("show", cmd_show), ("path", cmd_path)):
        c = sub.add_parser(name); c.add_argument("slug"); c.add_argument("id"); c.set_defaults(fn=fn)
    l = sub.add_parser("list"); l.add_argument("slug", nargs="?"); l.add_argument("--all", action="store_true"); l.set_defaults(fn=cmd_list)
    r = sub.add_parser("run"); r.add_argument("--set", dest="set_id"); r.add_argument("--terminal", dest="terminal"); r.set_defaults(fn=cmd_run)
    o = sub.add_parser("owner"); o.add_argument("dispatch"); o.set_defaults(fn=cmd_owner)
    h = sub.add_parser("handled"); hs = h.add_subparsers(dest="action", required=True)
    hst = hs.add_parser("start"); hst.add_argument("msg"); hst.add_argument("--seq"); hst.add_argument("--type", required=True)
    hst.add_argument("--from", dest="from_"); hst.add_argument("--kind", choices=["outside", "mission"]); hst.add_argument("--summary")
    han = hs.add_parser("answer"); han.add_argument("msg"); han.add_argument("--summary")
    hs.add_parser("get").add_argument("msg"); hs.add_parser("open")
    h.set_defaults(fn=cmd_handled)
    sc = sub.add_parser("scan"); ss = sc.add_subparsers(dest="action", required=True)
    ss.add_parser("seed").add_argument("--run", required=True); ss.add_parser("floor")
    sp = ss.add_parser("pending"); sp.add_argument("--run", required=True); sp.add_argument("--limit", type=int, required=True)
    sa = ss.add_parser("advance"); sa.add_argument("--run", required=True); sa.add_argument("--limit", type=int, required=True)
    sc.set_defaults(fn=cmd_scan)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
