#!/usr/bin/env python3
"""A mission's git, file and PR steps, so the coordinator's allowlist needs one rule.

  mission_ops.py docs-commit <slug> <id> --scope S   # SKILL step 5: branch, copy, commit, then clean <repo>
  mission_ops.py prep-commit <slug> <id> --scope S   # Plan mode P1; prints the short sha
  mission_ops.py prep-status <slug> <id>             # P1 recovery: user committed them -> short sha, else exit 1
  mission_ops.py remove-old-plan <slug> <id>         # Plan mode Cleanup: untracked stages.plan.old_path -> rm
  mission_ops.py owner-repo <repo-path>              # intake: origin URL -> owner/repo
  mission_ops.py move-doc <slug> <id> --to <rel>     # Plan mode Switch: move the spec into <repo>/<rel>
  mission_ops.py push <slug> <id>                    # git push -u origin <branch>, mission branch only
  mission_ops.py pr-split <slug> <id> --scope S      # pr-body.md -> pr-title.txt + pr-body-rest.md
  mission_ops.py pr-create <slug> <id>               # gh pr create from those files -> {"number":N,"url":...}
  mission_ops.py greptile-delay <slug> <id> [--seconds 300]
  mission_ops.py merge-watch <slug> <id> [--interval 300] [--deadline 21600]
  mission_ops.py gate <slug> <id> <read|spec|plan|verify> [--repo key=path ...]
                                                     # one line: `pass` (exit 0) or `fail <n> <path>` (exit 1)
  mission_ops.py freeze-cases <slug> <id>            # cases_hash <- the spec's cases block; prints it
  mission_ops.py patterns-add <slug> <id> --stage S --key K [--class C]
  mission_ops.py patterns-escaped <slug> <id> --ticket T
  mission_ops.py patterns-repeat [--min 2] [--notice]  # keys seen in <min> or more missions, one JSON line each

Each one reads the mission with state.load and touches only its repo, worktree,
branch and files folder (ROOT/files/<slug>/<id>/). Exit codes: 0 ok, 3 refused or
bad mission, 2 merge-watch timeout, 1 prep-status not committed or a gate that failed; a failing git/gh step
passes its exit code through with its output on stderr. A gate reads only and writes only its own error file
`gate-<stage>.md` and the pattern log; `freeze-cases` is the one command here that writes mission state. Never --force, --no-verify or --amend.
"""
import argparse, json, os, re, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # python3 -I drops the script folder
import state  # noqa: E402
import gates  # noqa: E402

GIT_STATE = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply")


class Refused(Exception):
    pass


class Failed(Exception):
    def __init__(self, code, text):
        super().__init__(text)
        self.code = code


def git(path, *args, check=True):
    r = subprocess.run(["git", "-C", path, *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise Failed(r.returncode, (r.stderr + r.stdout).strip())
    return r


def stage(m, name, key):
    return ((m.get("stages") or {}).get(name) or {}).get(key) or ""


def files_dir(a):
    return os.path.join(state.ROOT, state.FILES, a.slug, a.id)


def message(m, kind, scope, title):
    ticket = m.get("ticket") or ""
    return (f"#{ticket} " if ticket else "") + f"{kind}({scope}): {title}"


def docs(m):
    """The spec and plan paths, once each (one file when spec-is-plan)."""
    out = []
    for p in (stage(m, "spec", "path"), stage(m, "plan", "path")):
        if p and p not in out:
            out.append(p)
    return out


def tracked(repo, path):
    """True unless `ls-files --error-unmatch` exits 1 (untracked)."""
    return git(repo, "ls-files", "--error-unmatch", "--", path, check=False).returncode != 1


def cmd_docs_commit(a, m):
    repo, wt, branch = m["repo"], stage(m, "worktree", "path"), stage(m, "worktree", "branch")
    srcs = docs(m)
    if not branch or not wt or not srcs:
        raise Refused("mission has no worktree branch, worktree path or spec/plan")
    rels = []
    for src in srcs:  # validate every source before any git step
        rel = os.path.relpath(src, repo)
        if rel.startswith(".."):
            raise Refused(f"{src} is outside {repo}")
        rels.append(rel)
    on_branch = git(wt, "symbolic-ref", "-q", "--short", "HEAD", check=False).stdout.strip() == branch
    for src, rel in zip(srcs, rels):
        # a re-run after success: the source is gone but the branch already has the file
        if not os.path.exists(src) and not (on_branch and tracked(wt, rel)):
            raise Refused(f"{src} is missing")
    if not on_branch:  # a re-run after a failed commit is already on the branch
        git(wt, "switch", "-c", branch)
    for src, rel in zip(srcs, rels):
        if os.path.exists(src):
            os.makedirs(os.path.dirname(os.path.join(wt, rel)), exist_ok=True)
            shutil.copyfile(src, os.path.join(wt, rel))
    git(wt, "add", "--", *rels)
    if git(wt, "diff", "--cached", "--quiet", "--", *rels, check=False).returncode != 0:
        git(wt, "commit", "-m", message(m, "docs", a.scope, "add spec and plan"), "--", *rels)
    kept, removed = [], []
    for src in srcs:
        if not os.path.exists(src):
            continue
        if tracked(repo, src):
            kept.append(src)
        else:
            os.remove(src)
            removed.append(src)
    print(json.dumps({"kept": kept, "removed": removed}))


def prep_paths(m):
    """[spec, plan], both under <repo>/<prep_dir>; else Refused."""
    prep = os.path.join(m["repo"], m.get("prep_dir") or "") + os.sep
    paths = [stage(m, "spec", "path"), stage(m, "plan", "path")]
    if not m.get("prep_dir") or not all(p.startswith(prep) for p in paths):
        raise Refused(f"spec and plan must be under {prep}")
    return paths


def cmd_prep_commit(a, m):
    repo = m["repo"]
    paths = prep_paths(m)
    if git(repo, "symbolic-ref", "-q", "HEAD", check=False).returncode != 0:
        raise Refused("detached HEAD")
    for name in GIT_STATE:
        p = git(repo, "rev-parse", "--path-format=absolute", "--git-path", name).stdout.strip()
        if os.path.exists(p):
            raise Refused(f"{name} exists: merge, cherry-pick, revert or rebase in progress")
    try:
        git(repo, "add", "--", *paths)
        git(repo, "commit", "-m", message(m, "docs", a.scope, "add spec and plan"), "--", *paths)
    except Failed:  # the add ran (a failed add may still stage part): unstage both again
        git(repo, "reset", "-q", "--", *paths, check=False)
        raise
    print(git(repo, "rev-parse", "--short", "HEAD").stdout.strip())


def cmd_prep_status(a, m):
    repo, paths = m["repo"], prep_paths(m)
    if git(repo, "status", "--porcelain", "--", *paths).stdout.strip():
        return 1
    sha = git(repo, "log", "-1", "--format=%h", "--", paths[1]).stdout.strip()
    if not sha:
        return 1
    print(sha)


def cmd_remove_old_plan(a, m):
    repo, old = m["repo"], stage(m, "plan", "old_path")
    if not old:
        print(json.dumps({"removed": [], "kept": []}))
        return
    if os.path.relpath(old, repo).startswith(".."):
        raise Refused(f"{old} is outside {repo}")
    if tracked(repo, old):
        print(json.dumps({"kept": [old]}))
    else:
        os.remove(old)
        print(json.dumps({"removed": [old]}))


OWNER_RE = re.compile(r"^(?:git@github\.com:|https://github\.com/)([^/\s]+)/([^/\s]+?)(?:\.git)?/?$")


def owner_repo(repo):
    r = git(repo, "remote", "get-url", "origin", check=False)
    hit = OWNER_RE.match(r.stdout.strip()) if r.returncode == 0 else None
    if not hit:
        raise Refused(f"no GitHub origin in {repo}: {(r.stdout + r.stderr).strip()}")
    return f"{hit.group(1)}/{hit.group(2)}"


def cmd_move_doc(a, m):
    repo, src = m["repo"], stage(m, "spec", "path")
    dst = os.path.join(repo, a.to)
    if not src or os.path.relpath(dst, repo).startswith(".."):
        raise Refused("no spec path, or --to is outside the repo")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if tracked(repo, src):
        shutil.copyfile(src, dst)
        action = "copied"
    else:
        shutil.move(src, dst)
        action = "moved"
    print(json.dumps({"path": dst, "action": action}))


def cmd_push(a, m):
    wt, branch = stage(m, "worktree", "path"), stage(m, "worktree", "branch")
    if not wt or not branch:
        raise Refused("mission has no worktree path or branch")
    cur = git(wt, "symbolic-ref", "-q", "--short", "HEAD", check=False).stdout.strip()
    if cur != branch:
        raise Refused(f"current branch is {cur or '(detached)'}, not {branch}")
    r = git(wt, "push", "-u", "origin", branch)
    sys.stderr.write(r.stderr)


def cmd_pr_split(a, m):
    d = files_dir(a)
    with open(os.path.join(d, "pr-body.md")) as f:
        lines = f.read().splitlines(keepends=True)
    title = lines[0].rstrip("\n") if lines else ""
    if not title or len(title) > 70:
        title = message(m, "feat", a.scope, m.get("title") or "")
    state.write_text(os.path.join(d, "pr-title.txt"), title + "\n")
    state.write_text(os.path.join(d, "pr-body-rest.md"), "".join(lines[1:]))
    print(title)


def cmd_pr_create(a, m):
    d, branch, repo = files_dir(a), stage(m, "worktree", "branch"), m.get("owner_repo") or ""
    if not branch or not repo or not m.get("base_branch"):
        raise Refused("mission has no worktree branch, owner_repo or base_branch")
    with open(os.path.join(d, "pr-title.txt")) as f:
        title = f.read().strip("\n")
    r = subprocess.run(["gh", "pr", "create", "--repo", repo, "--base", m["base_branch"], "--head", branch,
                        "--title", title, "--body-file", os.path.join(d, "pr-body-rest.md")],
                       capture_output=True, text=True)
    if r.returncode == 0:
        url = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
        hit = re.search(r"/pull/(\d+)", url)
        print(json.dumps({"number": int(hit.group(1)) if hit else None, "url": url}))
        return 0
    # "Something went wrong" may still have made the PR: look before failing
    lst = subprocess.run(["gh", "pr", "list", "--repo", repo, "--head", branch, "--state", "all",
                          "--json", "number,url"], capture_output=True, text=True)
    try:
        prs = json.loads(lst.stdout) if lst.returncode == 0 else []
    except ValueError:
        prs = []
    if prs:
        print(json.dumps({"number": prs[0].get("number"), "url": prs[0].get("url")}))
        return 0
    raise Failed(r.returncode, (r.stderr + r.stdout).strip())


def pr_number(m):
    n = stage(m, "pr", "number")
    if not n:
        raise Refused("mission has no stages.pr.number")
    return str(n)


def cmd_greptile_delay(a, m):
    n = pr_number(m)
    time.sleep(a.seconds)
    print(f"greptile delay over for {a.id} PR {n}")


def cmd_merge_watch(a, m):
    n, deadline = pr_number(m), time.time() + a.deadline
    while time.time() < deadline:
        r = subprocess.run(["gh", "pr", "view", n, "--repo", m.get("owner_repo") or "",
                            "--json", "number,state,mergedAt,mergeCommit,closedAt"],
                           capture_output=True, text=True)
        out = r.stdout.strip() if r.returncode == 0 else ""
        try:
            st = json.loads(out).get("state", "")
        except Exception:
            st = ""
        if st in ("MERGED", "CLOSED"):
            state.write_text(os.path.join(files_dir(a), "pr-final.json"), out + "\n")
            print(f"PR {n} ({a.id}) is {st}: {out}")
            return 0
        time.sleep(a.interval)
    print(f"TIMEOUT: PR {n} still open after 6h")
    return 2


PATTERNS = "patterns.jsonl"  # ROOT/patterns.jsonl: one row per failure, across missions (design 5.14)
NOTICED = "patterns-noticed.json"  # keys that already got a repeat notice


def pattern_row(a, stage_name, key, klass="", escaped=False, ticket=""):
    row = {"at": state.now(), "mission": f"{a.slug}/{a.id}", "stage": stage_name, "key": key,
           "class": klass, "escaped": escaped, "ticket": ticket}
    state.append_text(os.path.join(state.ROOT, PATTERNS), json.dumps(row))


def read_patterns():
    p = os.path.join(state.ROOT, PATTERNS)
    if not os.path.exists(p):
        return []
    rows = []
    with open(p) as f:
        for line in f:
            if line.strip():
                try:
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError(line)
                except ValueError:
                    raise Refused(f"bad pattern file: {p}")
                rows.append(row)
    return rows


def gate_repos(a, m):
    """Repo key -> path for citations. Default: the mission's repo under its slug."""
    out = {}
    for item in a.repo or []:
        key, sep, path = item.partition("=")
        if not sep or not key or not path:
            raise Refused(f"--repo wants key=path, got {item}")
        out[key] = path
    if not out and m.get("repo"):
        out[a.slug] = m["repo"]
    return out


def cmd_gate(a, m):
    d = files_dir(a)
    findings, frozen = os.path.join(d, "requirement-findings.md"), m.get("cases_hash") or ""
    if a.stage not in ("read", "spec", "plan", "verify"):
        raise Refused(f"no gate for stage {a.stage}")
    repos = gate_repos(a, m)
    try:
        if a.stage == "read":
            errs = gates.gate_read(list(stage(m, "read", "paths") or []), repos, findings)
        elif a.stage == "spec":
            errs = gates.gate_spec(stage(m, "spec", "path"), findings)
        elif a.stage == "plan":
            errs = gates.gate_plan(stage(m, "plan", "path"), stage(m, "spec", "path"), frozen)
        else:
            errs = gates.gate_verify(os.path.join(d, "verify.json"), stage(m, "spec", "path"), frozen,
                                     stage(m, "worktree", "path"), os.path.join(d, "found-defects.md"), d)
    except Exception as e:  # a gate that breaks is not a gate that failed: exit 3, never exit 1 with no line
        raise Refused(f"gate {a.stage} broke: {type(e).__name__}: {e}")
    out = os.path.join(d, f"gate-{a.stage}.md")
    if not errs:
        if os.path.exists(out):  # the error list of an earlier, failed run of this gate
            os.remove(out)
        print("pass")
        return 0
    state.write_text(out, "".join(f"- {code}: {text}\n" for code, text in errs))
    for code in sorted({code for code, _ in errs}):
        pattern_row(a, a.stage, code)
    print(f"fail {len(errs)} {out}")
    return 1


def cmd_freeze_cases(a, m):
    block, cases = gates.parse_cases(gates.read_text(stage(m, "spec", "path")) or "")[:2]
    if block is None or not cases:
        raise Refused("the spec has no case in a cases block")
    m["cases_hash"] = gates.cases_hash(block)
    state.save(a.slug, a.id, m)
    print(m["cases_hash"])


def cmd_patterns_add(a, m):
    pattern_row(a, a.stage, a.key, a.klass or "")


def cmd_patterns_escaped(a, m):
    pattern_row(a, "escaped", "escaped", escaped=True, ticket=a.ticket)


def patterns_repeat(a):
    by = {}
    for row in read_patterns():
        by.setdefault(row.get("key") or "", set()).add(row.get("mission") or "")
    hits = {k: sorted(v) for k, v in sorted(by.items()) if k and len(v) >= a.min}
    for key, missions in hits.items():
        print(json.dumps({"key": key, "missions": missions}))
    if a.notice:
        p = os.path.join(state.ROOT, NOTICED)
        try:
            with open(p) as f:
                noticed = json.load(f)
            if not isinstance(noticed, list):
                raise ValueError(p)
        except FileNotFoundError:
            noticed = []
        except ValueError:
            raise Refused(f"bad file: {p}")
        for key, missions in hits.items():
            if key not in noticed:  # one writer (the coordinator); a crash here can repeat a notice, never lose one
                state.notice_add("pattern", f"repeat pattern {key}: {', '.join(missions)}")
                noticed.append(key)
                state.write_json(p, noticed)
    return 0


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("owner-repo").add_argument("repo_path")
    pr = sub.add_parser("patterns-repeat")
    pr.add_argument("--min", type=int, default=2)
    pr.add_argument("--notice", action="store_true")
    cmds = {}
    for name, fn in (("docs-commit", cmd_docs_commit), ("prep-commit", cmd_prep_commit),
                     ("prep-status", cmd_prep_status), ("remove-old-plan", cmd_remove_old_plan),
                     ("move-doc", cmd_move_doc), ("push", cmd_push), ("pr-split", cmd_pr_split),
                     ("pr-create", cmd_pr_create), ("gate", cmd_gate), ("freeze-cases", cmd_freeze_cases),
                     ("patterns-add", cmd_patterns_add), ("patterns-escaped", cmd_patterns_escaped),
                     ("greptile-delay", cmd_greptile_delay), ("merge-watch", cmd_merge_watch)):
        s = sub.add_parser(name)
        s.add_argument("slug")
        s.add_argument("id")
        cmds[name] = (fn, s)
    for name in ("docs-commit", "prep-commit", "pr-split"):
        cmds[name][1].add_argument("--scope", required=True)
    cmds["move-doc"][1].add_argument("--to", required=True)
    cmds["gate"][1].add_argument("stage")
    cmds["gate"][1].add_argument("--repo", action="append")
    cmds["patterns-add"][1].add_argument("--stage", required=True)
    cmds["patterns-add"][1].add_argument("--key", required=True)
    cmds["patterns-add"][1].add_argument("--class", dest="klass")
    cmds["patterns-escaped"][1].add_argument("--ticket", required=True)
    cmds["greptile-delay"][1].add_argument("--seconds", type=float, default=300)
    cmds["merge-watch"][1].add_argument("--interval", type=float, default=300)
    cmds["merge-watch"][1].add_argument("--deadline", type=float, default=6 * 3600)
    a = p.parse_args()
    if a.cmd == "owner-repo":  # intake: runs before the mission exists
        try:
            print(owner_repo(a.repo_path))
            return 0
        except Refused as e:
            print(f"refused: {e}", file=sys.stderr)
            return 3
    if a.cmd == "patterns-repeat":  # across missions: no mission argument
        try:
            return patterns_repeat(a)
        except Refused as e:
            print(f"refused: {e}", file=sys.stderr)
            return 3
    try:
        m = state.load(a.slug, a.id)
    except (OSError, ValueError) as e:
        print(f"mission {a.slug}/{a.id}: {e}", file=sys.stderr)
        return 3
    try:
        return cmds[a.cmd][0](a, m) or 0
    except Refused as e:
        print(f"refused: {e}", file=sys.stderr)
        return 3
    except Failed as e:
        print(str(e), file=sys.stderr)
        return e.code
    except OSError as e:
        print(str(e), file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
