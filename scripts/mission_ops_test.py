"""Tests for mission_ops.py. Run from the repo root: python3 -I scripts/mission_ops_test.py -v

Each test builds a temp git repo (origin = a bare temp repo), puts a fake `gh` first
on PATH and points HOME at a temp folder, so nothing touches real missions or GitHub.
"""
import json, os, stat, subprocess, sys, tempfile, unittest

OPS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mission_ops.py")


def git(*args, check=True):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=check)


class OpsCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        t = os.path.realpath(self._tmp.name)
        self.home = os.path.join(t, "home")
        self.root = os.path.join(self.home, ".claude", "pipeline")
        self.files = os.path.join(self.root, "files", "app", "m1")
        self.bin = os.path.join(t, "bin")
        os.makedirs(self.bin)
        self.origin = os.path.join(t, "origin.git")
        git("init", "-q", "--bare", "-b", "main", self.origin)
        self.repo = os.path.join(t, "repo")
        git("init", "-q", "-b", "main", self.repo)
        for k, v in (("user.email", "t@t"), ("user.name", "t"), ("commit.gpgsign", "false")):
            git("-C", self.repo, "config", k, v)
        self.write(os.path.join(self.repo, "README.md"), "hi\n")
        git("-C", self.repo, "add", "README.md")
        git("-C", self.repo, "commit", "-q", "-m", "init")
        git("-C", self.repo, "remote", "add", "origin", self.origin)
        git("-C", self.repo, "push", "-q", "origin", "main")
        self.wt = os.path.join(t, "wt")
        git("-C", self.repo, "worktree", "add", "-q", "--detach", self.wt, "main")

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def read(self, path):
        with open(path) as f:
            return f.read()

    def mission(self, ticket="WBS-1", spec="", plan="", branch="feature/m1-x", pr=7, prep_dir="docs/preparation/m1",
                old_path=""):
        m = {"id": "m1", "ticket": ticket, "title": "Add thing", "repo": self.repo,
             "base_branch": "main", "owner_repo": "o/r", "mode": "full", "prep_dir": prep_dir,
             "stages": {"spec": {"path": spec}, "plan": {"path": plan, "old_path": old_path},
                        "worktree": {"path": self.wt, "branch": branch}, "pr": {"number": pr}}}
        self.write(os.path.join(self.root, "app", "m1.json"), json.dumps(m))

    def prep(self):
        d = os.path.join(self.repo, "docs/preparation/m1")
        spec, plan = os.path.join(d, "spec.md"), os.path.join(d, "plan.html")
        self.write(spec, "s\n")
        self.write(plan, "p\n")
        self.mission(spec=spec, plan=plan)
        return spec, plan

    def fake_gh(self, body):
        p = os.path.join(self.bin, "gh")
        self.write(p, "#!/bin/sh\n" + body)
        os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)

    def ops(self, *args):
        env = {**os.environ, "HOME": self.home, "PATH": self.bin + os.pathsep + os.environ["PATH"]}
        return subprocess.run([sys.executable, "-I", OPS, *args], env=env, capture_output=True, text=True)


class DocsCommitTest(OpsCase):
    def test_docs_commit_removes_untracked_keeps_tracked(self):
        spec = os.path.join(self.repo, "docs/spec.md")
        plan = os.path.join(self.repo, "docs/plan.html")
        self.write(spec, "spec\n")
        git("-C", self.repo, "add", "docs/spec.md")
        git("-C", self.repo, "commit", "-q", "-m", "spec")
        self.write(plan, "plan\n")
        self.mission(spec=spec, plan=plan)
        r = self.ops("docs-commit", "app", "m1", "--scope", "core")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {"kept": [spec], "removed": [plan]})
        self.assertTrue(os.path.exists(spec))
        self.assertFalse(os.path.exists(plan))
        self.assertEqual(git("-C", self.wt, "branch", "--show-current").stdout.strip(), "feature/m1-x")
        self.assertEqual(git("-C", self.wt, "log", "-1", "--format=%s").stdout.strip(),
                         "#WBS-1 docs(core): add spec and plan")
        self.assertEqual(self.read(os.path.join(self.wt, "docs/plan.html")), "plan\n")

    def test_docs_commit_no_ticket_message(self):
        spec = os.path.join(self.repo, "docs/spec.md")
        self.write(spec, "spec\n")
        self.mission(ticket="", spec=spec, plan=spec)
        r = self.ops("docs-commit", "app", "m1", "--scope", "core")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {"kept": [], "removed": [spec]})
        self.assertEqual(git("-C", self.wt, "log", "-1", "--format=%s").stdout.strip(),
                         "docs(core): add spec and plan")

    def docs_mission(self):
        spec = os.path.join(self.repo, "docs/spec.md")
        plan = os.path.join(self.repo, "docs/plan.html")
        self.write(spec, "spec\n")
        self.write(plan, "plan\n")
        self.mission(spec=spec, plan=plan)
        return spec, plan

    def test_docs_commit_rerun_after_hook_failure(self):
        spec, plan = self.docs_mission()
        hook = os.path.join(self.repo, ".git", "hooks", "pre-commit")
        self.write(hook, "#!/bin/sh\necho hook says no >&2\nexit 1\n")
        os.chmod(hook, 0o755)
        r = self.ops("docs-commit", "app", "m1", "--scope", "core")
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue(os.path.exists(spec))
        os.remove(hook)
        r = self.ops("docs-commit", "app", "m1", "--scope", "core")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {"kept": [], "removed": [spec, plan]})
        self.assertEqual(git("-C", self.wt, "log", "-1", "--format=%s").stdout.strip(),
                         "#WBS-1 docs(core): add spec and plan")

    def test_docs_commit_rerun_after_success_noop(self):
        self.docs_mission()
        self.assertEqual(self.ops("docs-commit", "app", "m1", "--scope", "core").returncode, 0)
        head = git("-C", self.wt, "rev-parse", "HEAD").stdout
        r = self.ops("docs-commit", "app", "m1", "--scope", "core")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {"kept": [], "removed": []})
        self.assertEqual(git("-C", self.wt, "rev-parse", "HEAD").stdout, head)

    def test_docs_commit_source_outside_repo_refused_before_switch(self):
        out = os.path.join(self.home, "spec.md")
        self.write(out, "s\n")
        self.mission(spec=out, plan=out)
        r = self.ops("docs-commit", "app", "m1", "--scope", "core")
        self.assertEqual(r.returncode, 3)
        self.assertEqual(git("-C", self.wt, "branch", "--show-current").stdout.strip(), "")

    def test_docs_commit_no_branch_exit3(self):
        self.mission(branch="")
        self.assertEqual(self.ops("docs-commit", "app", "m1", "--scope", "core").returncode, 3)


class PrepCommitTest(OpsCase):
    def test_prep_commit_ok(self):
        self.prep()
        r = self.ops("prep-commit", "app", "m1", "--scope", "core")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), git("-C", self.repo, "rev-parse", "--short", "HEAD").stdout.strip())

    def test_prep_commit_refuses_detached_head(self):
        self.prep()
        git("-C", self.repo, "checkout", "-q", "--detach")
        r = self.ops("prep-commit", "app", "m1", "--scope", "core")
        self.assertEqual(r.returncode, 3)
        self.assertIn("detached", r.stderr)

    def test_prep_commit_resets_on_hook_failure(self):
        self.prep()
        hook = os.path.join(self.repo, ".git", "hooks", "pre-commit")
        self.write(hook, "#!/bin/sh\necho hook says no >&2\nexit 1\n")
        os.chmod(hook, 0o755)
        head = git("-C", self.repo, "rev-parse", "HEAD").stdout
        r = self.ops("prep-commit", "app", "m1", "--scope", "core")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("hook says no", r.stderr)
        self.assertEqual(git("-C", self.repo, "diff", "--cached", "--name-only").stdout, "")
        self.assertEqual(git("-C", self.repo, "rev-parse", "HEAD").stdout, head)


class PrepStatusTest(OpsCase):
    def test_prep_status_committed_prints_sha(self):
        spec, plan = self.prep()
        git("-C", self.repo, "add", "--", spec, plan)
        git("-C", self.repo, "commit", "-q", "-m", "user commit")
        r = self.ops("prep-status", "app", "m1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), git("-C", self.repo, "rev-parse", "--short", "HEAD").stdout.strip())

    def test_prep_status_uncommitted_exit1(self):
        self.prep()
        r = self.ops("prep-status", "app", "m1")
        self.assertEqual((r.returncode, r.stdout), (1, ""))


class RemoveOldPlanTest(OpsCase):
    def test_remove_old_plan_untracked_removed(self):
        old = os.path.join(self.repo, "docs/plan.html")
        self.write(old, "p\n")
        self.mission(old_path=old)
        r = self.ops("remove-old-plan", "app", "m1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {"removed": [old]})
        self.assertFalse(os.path.exists(old))

    def test_remove_old_plan_tracked_kept(self):
        old = os.path.join(self.repo, "README.md")
        self.mission(old_path=old)
        r = self.ops("remove-old-plan", "app", "m1")
        self.assertEqual(json.loads(r.stdout), {"kept": [old]})
        self.assertTrue(os.path.exists(old))

    def test_remove_old_plan_empty_noop(self):
        self.mission()
        r = self.ops("remove-old-plan", "app", "m1")
        self.assertEqual((r.returncode, json.loads(r.stdout)), (0, {"removed": [], "kept": []}))


class OwnerRepoTest(OpsCase):
    def owner(self, url):
        git("-C", self.repo, "remote", "set-url", "origin", url)
        return self.ops("owner-repo", self.repo)

    def test_owner_repo_ssh(self):
        self.assertEqual(self.owner("git@github.com:acme/app.git").stdout, "acme/app\n")

    def test_owner_repo_https(self):
        self.assertEqual(self.owner("https://github.com/acme/app").stdout, "acme/app\n")
        self.assertEqual(self.owner("https://github.com/acme/app.git").stdout, "acme/app\n")

    def test_owner_repo_no_origin(self):
        git("-C", self.repo, "remote", "remove", "origin")
        self.assertEqual(self.ops("owner-repo", self.repo).returncode, 3)


class MoveDocTest(OpsCase):
    def test_move_doc_untracked_moves(self):
        spec = os.path.join(self.repo, "docs/spec.md")
        self.write(spec, "s\n")
        self.mission(spec=spec)
        r = self.ops("move-doc", "app", "m1", "--to", "docs/preparation/m1/spec.md")
        self.assertEqual(r.returncode, 0, r.stderr)
        new = os.path.join(self.repo, "docs/preparation/m1/spec.md")
        self.assertEqual(json.loads(r.stdout), {"path": new, "action": "moved"})
        self.assertFalse(os.path.exists(spec))


class PushTest(OpsCase):
    def test_push_refuses_other_branch(self):
        git("-C", self.wt, "switch", "-q", "-c", "other")
        self.mission()
        r = self.ops("push", "app", "m1")
        self.assertEqual(r.returncode, 3)
        self.assertEqual(git("-C", self.origin, "branch", "--list", "other").stdout, "")

    def test_push_ok(self):
        git("-C", self.wt, "switch", "-q", "-c", "feature/m1-x")
        self.mission()
        r = self.ops("push", "app", "m1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("feature/m1-x", git("-C", self.origin, "branch", "--list").stdout)


class PrSplitTest(OpsCase):
    def test_pr_split_long_title_falls_back(self):
        self.mission()
        self.write(os.path.join(self.files, "pr-body.md"), "x" * 71 + "\nbody line\n")
        r = self.ops("pr-split", "app", "m1", "--scope", "core")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "#WBS-1 feat(core): Add thing\n")
        self.assertEqual(self.read(os.path.join(self.files, "pr-title.txt")), "#WBS-1 feat(core): Add thing\n")
        self.assertEqual(self.read(os.path.join(self.files, "pr-body-rest.md")), "body line\n")

    def test_pr_split_keeps_short_title(self):
        self.mission()
        self.write(os.path.join(self.files, "pr-body.md"), "Short title\nrest\n")
        r = self.ops("pr-split", "app", "m1", "--scope", "core")
        self.assertEqual(r.stdout, "Short title\n")


class PrCreateTest(OpsCase):
    def setUp(self):
        super().setUp()
        self.mission()
        self.write(os.path.join(self.files, "pr-title.txt"), "#WBS-1 feat(core): it's \"x\"\n")
        self.write(os.path.join(self.files, "pr-body-rest.md"), "body\n")
        self.log = os.path.join(self.home, "gh.log")

    def gh(self, create_rc, list_out="[]"):
        self.fake_gh(f"""for a in "$@"; do printf '%s\\n' "$a"; done >> '{self.log}'; echo --- >> '{self.log}'
if [ "$2" = create ]; then
  [ {create_rc} -eq 0 ] && echo https://github.com/o/r/pull/9 && exit 0
  echo 'Something went wrong' >&2; exit {create_rc}
fi
echo '{list_out}'
""")

    def calls(self):
        return [c.strip("\n").split("\n") for c in self.read(self.log).split("---\n") if c.strip()]

    def test_pr_create_ok(self):
        self.gh(0)
        r = self.ops("pr-create", "app", "m1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {"number": 9, "url": "https://github.com/o/r/pull/9"})
        self.assertEqual(self.calls()[0], ["pr", "create", "--repo", "o/r", "--base", "main", "--head", "feature/m1-x",
                                           "--title", '#WBS-1 feat(core): it\'s "x"', "--body-file",
                                           os.path.join(self.files, "pr-body-rest.md")])

    def test_pr_create_failed_but_exists(self):
        self.gh(1, '[{"number":9,"url":"u9"}]')
        r = self.ops("pr-create", "app", "m1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {"number": 9, "url": "u9"})
        self.assertEqual(self.calls()[1], ["pr", "list", "--repo", "o/r", "--head", "feature/m1-x",
                                           "--state", "all", "--json", "number,url"])

    def test_pr_create_failed_none_exists(self):
        self.gh(4)
        r = self.ops("pr-create", "app", "m1")
        self.assertEqual(r.returncode, 4)
        self.assertIn("Something went wrong", r.stderr)


class WatchTest(OpsCase):
    def test_greptile_delay(self):
        self.mission()
        r = self.ops("greptile-delay", "app", "m1", "--seconds", "0")
        self.assertEqual(r.stdout, "greptile delay over for m1 PR 7\n")

    def test_merge_watch_writes_final_on_merged(self):
        self.mission()
        self.fake_gh('echo \'{"number":7,"state":"MERGED","mergedAt":"x"}\'\n')
        r = self.ops("merge-watch", "app", "m1", "--interval", "0", "--deadline", "5")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("PR 7 (m1) is MERGED", r.stdout)
        self.assertEqual(json.loads(self.read(os.path.join(self.files, "pr-final.json")))["state"], "MERGED")

    def test_merge_watch_timeout_exit2(self):
        self.mission()
        self.fake_gh('echo \'{"number":7,"state":"OPEN"}\'\n')
        r = self.ops("merge-watch", "app", "m1", "--interval", "0.05", "--deadline", "0.3")
        self.assertEqual(r.returncode, 2)
        self.assertIn("TIMEOUT: PR 7 still open after 6h", r.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.files, "pr-final.json")))



SPEC_OK = """# Spec

## Goal
g

## Design
d

- RQ-01: settled

<!-- cases:start -->
### VC-01 The note shows
family: main
- [mobile] open the job
expected: the note is in the list

- no error case: nothing can fail here
- no permission case: no right of its own
<!-- cases:end -->
"""
PLAN_OK = "<!-- case-tasks:start -->\nVC-01: T1\n<!-- case-tasks:end -->\ntier: mobile\n"


class GateTest(OpsCase):
    """`gate`, `freeze-cases` and the pattern log (verification loop slice 1)."""

    def setUp(self):
        super().setUp()
        self.spec = os.path.join(self.repo, "docs/spec.md")
        self.plan = os.path.join(self.repo, "docs/plan.md")
        self.write(self.spec, SPEC_OK)
        self.write(self.plan, PLAN_OK)
        self.write(os.path.join(self.files, "requirement-findings.md"), "- RQ-01 | ambiguous | s | none\n")
        self.mission(spec=self.spec, plan=self.plan)
        self.state = os.path.join(self.root, "app", "m1.json")
        self.patterns = os.path.join(self.root, "patterns.jsonl")

    def set(self, **kv):
        m = json.loads(self.read(self.state))
        m.update(kv)
        self.write(self.state, json.dumps(m))

    def rows(self):
        return [json.loads(l) for l in self.read(self.patterns).splitlines()] if os.path.exists(self.patterns) else []

    def test_spec_gate_pass_prints_one_word(self):
        r = self.ops("gate", "app", "m1", "spec")
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "pass\n", ""))
        self.assertFalse(os.path.exists(os.path.join(self.files, "gate-spec.md")))
        self.assertEqual(self.rows(), [])

    def test_spec_gate_fail_writes_the_list_and_the_patterns_then_clears(self):
        self.write(self.spec, SPEC_OK.replace("expected: the note is in the list\n", "").replace("- RQ-01: settled\n", ""))
        r = self.ops("gate", "app", "m1", "spec")
        out = os.path.join(self.files, "gate-spec.md")
        self.assertEqual((r.returncode, r.stdout), (1, f"fail 2 {out}\n"))
        self.assertEqual([l.split(":")[0] for l in self.read(out).splitlines()],
                         ["- SPEC-CASE-EXPECTED", "- SPEC-FINDING-UNRESOLVED"])
        self.assertEqual([(x["mission"], x["stage"], x["key"], x["escaped"]) for x in self.rows()],
                         [("app/m1", "spec", "SPEC-CASE-EXPECTED", False), ("app/m1", "spec", "SPEC-FINDING-UNRESOLVED", False)])
        self.write(self.spec, SPEC_OK)
        self.assertEqual(self.ops("gate", "app", "m1", "spec").stdout, "pass\n")
        self.assertFalse(os.path.exists(out))

    def test_gate_does_not_write_mission_state(self):
        before = self.read(self.state)
        self.ops("gate", "app", "m1", "spec")
        self.ops("gate", "app", "m1", "plan")
        self.assertEqual(self.read(self.state), before)

    def test_unknown_stage_and_bad_repo_are_refused(self):
        self.assertEqual(self.ops("gate", "app", "m1", "build").returncode, 3)
        self.assertEqual(self.ops("gate", "app", "m1", "read", "--repo", "nokey").returncode, 3)
        self.assertEqual(self.ops("gate", "app", "nope", "spec").returncode, 3)

    def test_read_gate_uses_the_mission_repo_or_the_given_keys(self):
        readings = os.path.join(self.files, "readings", "ui.md")
        self.write(readings, "[app:README.md:1]\n\n## Could not verify\nnone\n")
        m = json.loads(self.read(self.state))
        m["stages"]["read"] = {"paths": [readings]}
        self.write(self.state, json.dumps(m))
        self.assertEqual(self.ops("gate", "app", "m1", "read").stdout, "pass\n")
        r = self.ops("gate", "app", "m1", "read", "--repo", f"web={self.repo}")
        self.assertEqual(r.returncode, 1)
        self.assertIn("READ-REPO-UNKNOWN", self.read(os.path.join(self.files, "gate-read.md")))
        self.assertEqual(self.ops("gate", "app", "m1", "read", "--repo", f"app={self.repo}", "--repo", f"web={self.wt}").stdout,
                         "pass\n")

    def test_freeze_cases_then_the_plan_gate_sees_a_change(self):
        r = self.ops("freeze-cases", "app", "m1")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(json.loads(self.read(self.state))["cases_hash"], r.stdout.strip())
        self.assertEqual(len(r.stdout.strip()), 64)
        self.assertEqual(self.ops("gate", "app", "m1", "plan").stdout, "pass\n")
        self.write(self.spec, SPEC_OK.replace("the note is in the list", "something else"))
        self.assertEqual(self.ops("gate", "app", "m1", "plan").returncode, 1)
        self.assertIn("PLAN-CASES-CHANGED", self.read(os.path.join(self.files, "gate-plan.md")))

    def test_freeze_cases_refuses_a_spec_with_no_block(self):
        self.write(self.spec, "# Spec\n")
        self.assertEqual(self.ops("freeze-cases", "app", "m1").returncode, 3)

    def test_verify_gate_checks_the_worktree_head(self):
        frozen = self.ops("freeze-cases", "app", "m1").stdout.strip()
        head = git("-C", self.wt, "rev-parse", "HEAD").stdout.strip()
        self.write(os.path.join(self.files, "evidence", "a.txt"), "x")
        report = {"commit": head, "cases_hash": frozen, "verdict": "VERIFIED", "rows": [
            {"case": "VC-01", "result": "pass", "class": "", "baseline": "fail",
             "evidence": [{"kind": "screen", "path": "evidence/a.txt"}]}]}
        self.write(os.path.join(self.files, "verify.json"), json.dumps(report))
        self.assertEqual(self.ops("gate", "app", "m1", "verify").stdout, "pass\n")
        self.write(os.path.join(self.files, "verify.json"), json.dumps({**report, "commit": "0" * 40}))
        self.assertEqual(self.ops("gate", "app", "m1", "verify").returncode, 1)
        self.assertIn("VERIFY-COMMIT-STALE", self.read(os.path.join(self.files, "gate-verify.md")))

    def test_patterns_add_repeat_and_notice_once(self):
        self.write(os.path.join(self.root, "app", "m2.json"), json.dumps({"id": "m2"}))
        self.assertEqual(self.ops("patterns-add", "app", "m1", "--stage", "verify", "--key", "verify:bug-app", "--class", "bug-app").returncode, 0)
        self.assertEqual(self.ops("patterns-add", "app", "m1", "--stage", "verify", "--key", "verify:bug-app").returncode, 0)
        self.assertEqual(self.ops("patterns-repeat").stdout, "")  # one mission only
        self.ops("patterns-add", "app", "m2", "--stage", "verify", "--key", "verify:bug-app")
        self.ops("patterns-add", "app", "m2", "--stage", "spec", "--key", "SPEC-NO-CASES")
        r = self.ops("patterns-repeat", "--notice")
        self.assertEqual(json.loads(r.stdout), {"key": "verify:bug-app", "missions": ["app/m1", "app/m2"]})
        self.ops("patterns-repeat", "--notice")
        notices = self.read(os.path.join(self.root, "notices.jsonl")).splitlines()
        self.assertEqual(len(notices), 1)
        self.assertEqual(json.loads(notices[0])["kind"], "pattern")
        self.assertEqual(self.ops("patterns-repeat", "--min", "3").stdout, "")

    def test_patterns_escaped_and_a_corrupt_file(self):
        self.assertEqual(self.ops("patterns-escaped", "app", "m1", "--ticket", "WBS-9").returncode, 0)
        row = self.rows()[0]
        self.assertEqual((row["escaped"], row["ticket"], row["key"]), (True, "WBS-9", "escaped"))
        self.write(self.patterns, "not json\n")
        self.assertEqual(self.ops("patterns-repeat").returncode, 3)

if __name__ == "__main__":
    unittest.main()
