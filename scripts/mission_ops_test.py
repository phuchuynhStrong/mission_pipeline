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

    def mission(self, ticket="WBS-1", spec="", plan="", branch="feature/m1-x", pr=7, prep_dir="docs/preparation/m1"):
        m = {"id": "m1", "ticket": ticket, "title": "Add thing", "repo": self.repo,
             "base_branch": "main", "owner_repo": "o/r", "mode": "full", "prep_dir": prep_dir,
             "stages": {"spec": {"path": spec}, "plan": {"path": plan},
                        "worktree": {"path": self.wt, "branch": branch}, "pr": {"number": pr}}}
        self.write(os.path.join(self.root, "app", "m1.json"), json.dumps(m))

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

    def test_docs_commit_no_branch_exit3(self):
        self.mission(branch="")
        self.assertEqual(self.ops("docs-commit", "app", "m1", "--scope", "core").returncode, 3)


class PrepCommitTest(OpsCase):
    def prep(self):
        d = os.path.join(self.repo, "docs/preparation/m1")
        spec, plan = os.path.join(d, "spec.md"), os.path.join(d, "plan.html")
        self.write(spec, "s\n")
        self.write(plan, "p\n")
        self.mission(spec=spec, plan=plan)
        return spec, plan

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


if __name__ == "__main__":
    unittest.main()
