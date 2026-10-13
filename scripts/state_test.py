"""Tests for state.py. Run from the repo root: python3 -I scripts/state_test.py -v

Each test runs state.py as a CLI with HOME pointed at a temp folder, so ROOT is
<tmp>/.claude/pipeline and nothing touches the real mission files.
"""
import json, os, subprocess, sys, tempfile, unittest

STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.py")


class StateCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = self._tmp.name
        self.root = os.path.join(self.home, ".claude", "pipeline")
        self.coord = os.path.join(self.root, "coordinator.json")

    def tearDown(self):
        self._tmp.cleanup()

    def state(self, *args):
        return subprocess.run(
            [sys.executable, "-I", STATE, *args],
            env={**os.environ, "HOME": self.home}, capture_output=True, text=True,
        )

    def write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def read(self, path):
        with open(path) as f:
            return f.read()

    def mission(self, slug, mid, stage="read", dispatches=None, settled=None):
        m = {"id": mid, "stage": stage, "note": ""}
        if dispatches is not None:
            m["dispatches"] = dispatches
        if settled is not None:
            m["settled"] = settled
        self.write(os.path.join(self.root, slug, f"{mid}.json"), json.dumps(m))


class RunTest(StateCase):
    def test_run_no_file_prints_empty(self):
        r = self.state("run")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "\n")

    def test_run_set_then_get(self):
        self.assertEqual(self.state("run", "--set", "run_a").returncode, 0)
        r = self.state("run")
        self.assertEqual((r.returncode, r.stdout), (0, "run_a\n"))

    def test_run_set_keeps_created(self):
        self.state("run", "--set", "run_a")
        first = json.loads(self.read(self.coord))
        self.state("run", "--set", "run_b")
        second = json.loads(self.read(self.coord))
        self.assertEqual(second["run_id"], "run_b")
        self.assertEqual(second["created"], first["created"])

    def test_run_corrupt_file_exit3_unchanged(self):
        self.write(self.coord, "{not json")
        r = self.state("run")
        self.assertEqual(r.returncode, 3)
        self.assertEqual(self.read(self.coord), "{not json")

    def test_run_set_corrupt_file_exit3_unchanged(self):
        self.write(self.coord, "{not json")
        r = self.state("run", "--set", "run_a")
        self.assertEqual(r.returncode, 3)
        self.assertEqual(self.read(self.coord), "{not json")

    def test_run_file_without_run_id_exit3(self):
        self.write(self.coord, json.dumps({"created": "x"}))
        self.assertEqual(self.state("run").returncode, 3)

    def test_run_set_creates_root(self):
        self.assertFalse(os.path.exists(self.root))
        self.assertEqual(self.state("run", "--set", "run_a").returncode, 0)
        self.assertEqual(json.loads(self.read(self.coord))["run_id"], "run_a")

    def test_run_set_empty_refused(self):
        r = self.state("run", "--set", "")
        self.assertEqual(r.returncode, 3)
        self.assertFalse(os.path.exists(self.coord))


class NewListTest(StateCase):
    def test_list_ignores_coordinator_file(self):
        self.state("run", "--set", "run_a")
        self.mission("repo", "m1")
        r = self.state("list")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.splitlines(), ["repo/m1  stage=read  "])

    def test_new_requires_run_id(self):
        r = self.state("new", "repo", "m1", "--ticket", "T-1")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.root, "repo", "m1.json")))

    def test_new_writes_run_id_and_lists(self):
        r = self.state("new", "repo", "m1", "--run-id", "run_a")
        self.assertEqual(r.returncode, 0)
        m = json.loads(self.read(os.path.join(self.root, "repo", "m1.json")))
        self.assertEqual((m["run_id"], m["dispatches"], m["settled"]), ("run_a", [], []))

    def test_append_dispatch_keeps_string(self):
        self.state("new", "repo", "m1", "--run-id", "run_a")
        self.state("set", "repo", "m1", "dispatches+=123", "settled+=456")
        m = json.loads(self.read(os.path.join(self.root, "repo", "m1.json")))
        self.assertEqual((m["dispatches"], m["settled"]), (["123"], ["456"]))


class OwnerTest(StateCase):
    def test_owner_live_then_settled(self):
        self.mission("repo", "m1", dispatches=["ctx_a"], settled=[])
        r = self.state("owner", "ctx_a")
        self.assertEqual((r.returncode, r.stdout), (0, "repo m1 live\n"))
        self.mission("repo", "m1", dispatches=["ctx_a"], settled=["ctx_a"])
        r = self.state("owner", "ctx_a")
        self.assertEqual((r.returncode, r.stdout), (0, "repo m1 settled\n"))

    def test_owner_unknown_exit3(self):
        self.mission("repo", "m1", dispatches=["ctx_a"], settled=[])
        r = self.state("owner", "ctx_zz")
        self.assertEqual((r.returncode, r.stdout), (3, ""))

    def test_owner_skips_done_and_aborted(self):
        self.mission("repo", "m1", stage="done", dispatches=["ctx_a"], settled=[])
        self.mission("repo", "m2", stage="aborted", dispatches=["ctx_a"], settled=[])
        self.assertEqual(self.state("owner", "ctx_a").returncode, 3)

    def test_owner_duplicate_exit4_prints_both(self):
        self.mission("repo", "m1", dispatches=["ctx_a"], settled=[])
        self.mission("other", "m2", dispatches=["ctx_a"], settled=[])
        r = self.state("owner", "ctx_a")
        self.assertEqual(r.returncode, 4)
        self.assertEqual(sorted(r.stdout.splitlines()), ["other m2 live", "repo m1 live"])

    def test_owner_corrupt_mission_is_not_no_owner(self):
        self.mission("repo", "m1", dispatches=["ctx_a"], settled=[])
        self.write(os.path.join(self.root, "repo", "m0.json"), "{not json")
        r = self.state("owner", "ctx_a")
        self.assertNotIn(r.returncode, (0, 3))

    def test_owner_mission_without_lists(self):
        self.mission("repo", "m1")
        self.mission("repo", "m2", dispatches=["ctx_a"], settled=[])
        r = self.state("owner", "ctx_a")
        self.assertEqual((r.returncode, r.stdout), (0, "repo m2 live\n"))

    def test_owner_no_root(self):
        r = self.state("owner", "ctx_a")
        self.assertEqual((r.returncode, r.stdout), (3, ""))

    def test_owner_skips_stray_files(self):
        self.state("run", "--set", "run_a")
        self.write(os.path.join(self.root, ".DS_Store"), "x")
        self.write(os.path.join(self.root, "repo", ".DS_Store"), "x")
        self.write(os.path.join(self.root, "repo", "notes.txt"), "x")
        self.mission("repo", "m1", dispatches=["ctx_a"], settled=[])
        r = self.state("owner", "ctx_a")
        self.assertEqual((r.returncode, r.stdout), (0, "repo m1 live\n"))


if __name__ == "__main__":
    unittest.main()
