#!/usr/bin/env python3
"""Mission state for the pipeline skill. One JSON file per mission.

  state.py new  <repo-slug> <id> --ticket WBS-1 --title "..." --repo /abs --base-branch B
  state.py set  <repo-slug> <id> stage=spec stages.spec.status=active note="..." events+="text"
  state.py abort <repo-slug> <id> --reason "..."   # stage=aborted, open stages -> failed
  state.py done  <repo-slug> <id> --reason "..."   # stage=done (PR merged / user said so)
  state.py show <repo-slug> <id>
  state.py path <repo-slug> <id>
  state.py list [repo-slug] [--all]        # done/aborted missions hidden unless --all

Dotted keys walk nested dicts. A value is parsed as JSON when it parses,
else kept as a string. `key+=value` appends to a list.

`attention` is the board's switch button: set `attention.terminal=<handle>
attention.reason="<one line>"` when a mission waits on the user; `attention=null` clears it.
"""
import json, os, sys, argparse, datetime, tempfile

ROOT = os.path.join(os.path.expanduser("~"), ".claude", "pipeline")
STAGES = ["read", "spec", "plan", "worktree", "build", "review", "pr"]
TERMINAL = ["done", "aborted"]  # stage values the board treats as closed; "ready" (PR open, waiting merge) is still open


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def path_of(slug, mid):
    return os.path.join(ROOT, slug, f"{mid}.json")


def load(slug, mid):
    with open(path_of(slug, mid)) as f:
        return json.load(f)


def save(slug, mid, data):
    p = path_of(slug, mid)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    data["updated"] = now()
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(p), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, p)


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
        "repo": a.repo or "", "repo_slug": a.slug, "run_id": "",
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
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
