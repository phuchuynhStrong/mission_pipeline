"""Share of code searches that use the LSP tool, from Claude Code transcripts.

Run: python3 -I scripts/search_stats.py [--by kind|project|week] [--since YYYY-MM-DD]
                                          [--root DIR] [--json]
     python3 -I scripts/search_stats.py --health [--days 7]   (one JSON line, for /pboard)

Reads every transcript under ~/.claude/projects (main sessions, Orca workers and
subagents) and puts each search tool call in one bucket:

  lsp   the LSP tool, or the dart-mcp lsp tool
  grep  the Grep tool
  glob  the Glob tool
  bash  a Bash call where a command starts with grep, egrep, fgrep, rg, ag, ack,
        find or git grep. A grep after a pipe (`flutter analyze | grep`) filters
        output and is not a search, so it does not count.

Read is not a search. Each search gets a language from its path, glob, type or
command: dart, ts (TypeScript), or unknown when nothing names one. A search that
names both counts once under each language and once under "all".
"""
import argparse, collections, datetime, glob, json, os, re, sys

ROOT = os.path.expanduser("~/.claude/projects")
WORKER_MARK = "You are a dispatched worker"
LSP_TOOLS = {"LSP", "mcp__plugin_dart-flutter_dart-mcp-server__lsp"}
SEARCH_PROGRAMS = {"grep", "egrep", "fgrep", "rg", "ag", "ack", "find"}
METHODS = ("lsp", "grep", "glob", "bash")
LANGS = ("dart", "ts", "unknown", "all")

DART_RE = re.compile(r"\.dart\b|(?:-t|--type)[ =]?dart\b")
TS_RE = re.compile(r"\.(?:ts|tsx|mts|cts)\b|(?:-t|--type)[ =]?(?:ts|typescript)\b")
SPLIT_RE = re.compile(r"&&|\|\||;|\n")
ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=\S*$")


def langs_of(text):
    """Languages a search names: a subset of {"dart", "ts"}, or {"unknown"}."""
    found = set()
    if DART_RE.search(text or ""):
        found.add("dart")
    if TS_RE.search(text or ""):
        found.add("ts")
    return found or {"unknown"}


def first_program(command):
    """Program name of the first stage of one shell command, or ""."""
    head = command.split("|", 1)[0].strip().lstrip("({ ")
    words = [w for w in head.split() if not ENV_RE.match(w)]
    while words and words[0] in ("sudo", "command", "time", "nice", "exec"):
        words = words[1:]
    if not words:
        return ""
    prog = os.path.basename(words[0].strip("'\""))
    if prog == "git" and len(words) > 1 and words[1] == "grep":
        return "git grep"
    return prog


def is_bash_search(command):
    return any(
        first_program(part) in SEARCH_PROGRAMS or first_program(part) == "git grep"
        for part in SPLIT_RE.split(command or "")
    )


def classify(name, inp):
    """(method, langs) for a search tool call, or None when it is not a search."""
    inp = inp if isinstance(inp, dict) else {}
    if name in LSP_TOOLS:
        return "lsp", langs_of(str(inp.get("filePath") or inp.get("uri") or ""))
    if name == "Grep":
        type_flag = f"--type={inp['type']}" if inp.get("type") else ""
        return "grep", langs_of(" ".join(
            [str(inp.get("path") or ""), str(inp.get("glob") or ""), type_flag]))
    if name == "Glob":
        return "glob", langs_of(" ".join(
            str(inp.get(k) or "") for k in ("pattern", "path")))
    if name == "Bash" and is_bash_search(inp.get("command")):
        return "bash", langs_of(inp.get("command"))
    return None


def first_user_text(path):
    with open(path, errors="ignore") as f:
        for line in f:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("type") == "user":
                c = (e.get("message") or {}).get("content")
                return c if isinstance(c, str) else json.dumps(c)
    return ""


def session_kind(path):
    if os.sep + "subagents" + os.sep in path:
        return "subagent"
    return "worker" if WORKER_MARK in first_user_text(path) else "main"


def local_date(ts):
    """Local calendar date of a transcript timestamp (stored in UTC), or None."""
    try:
        return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().date()
    except (AttributeError, ValueError):
        return None


def transcripts(root, since=None):
    """Transcript paths; with `since`, only files changed on or after that local date."""
    for path in glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True):
        if since:
            try:
                if datetime.date.fromtimestamp(os.path.getmtime(path)) < since:
                    continue
            except OSError:
                continue
        yield path


def iter_searches(root, since=None):
    """Yield (kind, project, date, method, langs) for every search call.

    Only "assistant" entries count: other entry types (api-request-blob) repeat
    earlier tool calls. A tool_use id seen twice counts once.
    """
    for path in transcripts(root, since):
        project = os.path.relpath(path, root).split(os.sep)[0]
        kind, seen = None, set()
        with open(path, errors="ignore") as f:
            for line in f:
                if '"tool_use"' not in line:
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("type") != "assistant":
                    continue
                content = (e.get("message") or {}).get("content")
                if not isinstance(content, list):
                    continue
                for b in content:
                    if not isinstance(b, dict) or b.get("type") != "tool_use":
                        continue
                    if b.get("id"):
                        if b["id"] in seen:
                            continue
                        seen.add(b["id"])
                    hit = classify(b.get("name"), b.get("input"))
                    if hit:
                        kind = kind or session_kind(path)
                        yield kind, project, local_date(e.get("timestamp")), hit[0], hit[1]


def group_key(by, kind, project, day):
    if by == "kind":
        return kind
    if by == "project":
        return project
    return day.strftime("%G-W%V") if day else ""


def tally(searches, by, since=None):
    """{lang: {group: Counter(method)}}; "all" counts each search once."""
    out = {lang: collections.defaultdict(collections.Counter) for lang in LANGS}
    for kind, project, day, method, langs in searches:
        if since and (day is None or day < since):
            continue
        key = group_key(by, kind, project, day) or "(no date)"
        for lang in langs:
            out[lang][key][method] += 1
        out["all"][key][method] += 1
    return out


NO_SERVER_RE = re.compile(r"no lsp server|lsp server .*(?:failed|not (?:running|available))", re.I)


def result_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(b.get("text") or "") for b in content if isinstance(b, dict))
    return ""


def lsp_calls(root, since=None):
    """Sorted (timestamp, ok, text) for every LSP call that got a result.

    A result is an error when it is marked is_error, or when its text says no
    server answered. A call with no result (interrupted) is left out.
    """
    calls = []
    for path in transcripts(root, since):
        pending = {}
        with open(path, errors="ignore") as f:
            for line in f:
                if "tool_result" not in line and "lsp" not in line.lower():
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                content = (e.get("message") or {}).get("content")
                if not isinstance(content, list):
                    continue
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if (e.get("type") == "assistant" and b.get("type") == "tool_use"
                            and b.get("name") in LSP_TOOLS and b.get("id")):
                        pending[b["id"]] = e.get("timestamp") or ""
                    elif (e.get("type") == "user" and b.get("type") == "tool_result"
                            and b.get("tool_use_id") in pending):
                        ts = pending.pop(b["tool_use_id"])
                        text = result_text(b.get("content"))
                        ok = not b.get("is_error") and not NO_SERVER_RE.search(text)
                        calls.append((ts, ok, text))
    if since:
        calls = [c for c in calls if (local_date(c[0]) or datetime.date.min) >= since]
    return sorted(calls, key=lambda c: c[0])


def health(root, since):
    """One summary for the board: LSP call results plus the Dart LSP share."""
    calls = lsp_calls(root, since)
    dart = tally(iter_searches(root, since), "kind", since)["dart"]
    last = calls[-1] if calls else None
    return {
        "since": since.isoformat(),
        "lsp_ok": sum(1 for c in calls if c[1]),
        "lsp_err": sum(1 for c in calls if not c[1]),
        "last_at": last[0] if last else None,
        "last_ok": last[1] if last else None,
        "last_error": next((c[2].strip().replace("\n", " ")[:200]
                            for c in reversed(calls) if not c[1]), None),
        "dart_lsp": sum(c["lsp"] for c in dart.values()),
        "dart_total": sum(sum(c[m] for m in METHODS) for c in dart.values()),
    }


def rows(groups):
    result = []
    for key in sorted(groups):
        c = groups[key]
        total = sum(c[m] for m in METHODS)
        result.append({"group": key, "total": total, **{m: c[m] for m in METHODS},
                       "lsp_pct": round(100 * c["lsp"] / total, 1) if total else 0.0})
    return result


def print_table(title, table):
    print(f"\n{title}")
    if not table:
        print("  (no searches)")
        return
    width = max(len("group"), *(len(r["group"]) for r in table))
    head = f"  {'group':<{width}}  {'total':>6}  " + "  ".join(f"{m:>5}" for m in METHODS)
    print(head + "   LSP %")
    for r in table:
        print(f"  {r['group']:<{width}}  {r['total']:>6}  "
              + "  ".join(f"{r[m]:>5}" for m in METHODS) + f"  {r['lsp_pct']:>6.1f}")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--by", choices=("kind", "project", "week"), default="kind")
    p.add_argument("--since", type=datetime.date.fromisoformat, default=None,
                   help="YYYY-MM-DD in local time, inclusive")
    p.add_argument("--root", default=ROOT)
    p.add_argument("--json", action="store_true")
    p.add_argument("--health", action="store_true",
                   help="print one JSON line for the board: LSP call results and Dart share")
    p.add_argument("--days", type=int, default=7,
                   help="with --health and no --since: the last N local days, today included")
    a = p.parse_args(argv)
    if a.health:
        since = a.since or datetime.date.today() - datetime.timedelta(days=max(a.days, 1) - 1)
        print(json.dumps(health(a.root, since)))
        return 0
    data = tally(iter_searches(a.root, a.since), a.by, a.since)
    report = {lang: rows(data[lang]) for lang in LANGS}
    if a.json:
        json.dump(report, sys.stdout, indent=1)
        print()
        return 0
    titles = {"dart": "Dart", "ts": "TypeScript", "unknown": "No language named", "all": "All searches"}
    for lang in LANGS:
        print_table(titles[lang], report[lang])
    return 0


if __name__ == "__main__":
    sys.exit(main())
