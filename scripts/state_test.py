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

    def test_run_set_keeps_other_fields(self):
        self.write(self.coord, json.dumps({"run_id": "run_a", "created": "c", "terminal": "term_1", "x": 1}))
        self.assertEqual(self.state("run", "--set", "run_b").returncode, 0)
        d = json.loads(self.read(self.coord))
        self.assertEqual((d["run_id"], d["terminal"], d["x"], d["created"]), ("run_b", "term_1", 1, "c"))

    def test_run_terminal_sets_field(self):
        self.state("run", "--set", "run_a")
        self.assertEqual(self.state("run", "--terminal", "term_9").returncode, 0)
        d = json.loads(self.read(self.coord))
        self.assertEqual((d["terminal"], d["run_id"]), ("term_9", "run_a"))

    def test_run_terminal_without_file_exit3(self):
        self.assertEqual(self.state("run", "--terminal", "term_9").returncode, 3)
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


def inbox(*rows):
    return json.dumps({"ok": True, "result": {"messages": list(rows)}})


def row(seq, to="run:run_a", typ="question"):
    return {"id": f"msg_{seq}", "sequence": seq, "to_handle": to, "type": typ,
            "from_handle": "term_x", "payload": None, "body": "b", "subject": "s",
            "thread_id": None, "read": 1, "created_at": "2026-11-02T11:42:58Z"}


class HandledTest(StateCase):
    def test_handled_start_answer_get(self):
        self.assertEqual(self.state("handled", "start", "msg_1", "--seq", "1", "--type", "question").returncode, 0)
        self.assertEqual(self.state("handled", "get", "msg_1").stdout, "started\n")
        self.assertEqual(self.state("handled", "answer", "msg_1").returncode, 0)
        self.assertEqual(self.state("handled", "get", "msg_1").stdout, "answered\n")
        self.assertEqual(self.state("handled", "get", "msg_2").stdout, "none\n")

    def test_handled_start_requires_positive_seq(self):
        self.assertEqual(self.state("handled", "start", "msg_1", "--type", "q").returncode, 3)
        self.assertEqual(self.state("handled", "start", "msg_1", "--seq", "0", "--type", "q").returncode, 3)
        self.assertEqual(self.state("handled", "start", "msg_1", "--seq", "x", "--type", "q").returncode, 3)

    def test_handled_answer_without_start_exit3(self):
        self.assertEqual(self.state("handled", "answer", "msg_1").returncode, 3)

    def test_handled_open_lists_only_unanswered(self):
        self.state("handled", "start", "msg_1", "--seq", "1", "--type", "question")
        self.state("handled", "start", "msg_2", "--seq", "2", "--type", "question")
        self.state("handled", "answer", "msg_1")
        r = self.state("handled", "open")
        self.assertEqual(r.returncode, 0)
        lines = [json.loads(x) for x in r.stdout.splitlines()]
        self.assertEqual([x["msg_id"] for x in lines], ["msg_2"])

    def test_handled_corrupt_exit3(self):
        path = os.path.join(self.root, "handled.jsonl")
        self.write(path, "{not json\n")
        r = self.state("handled", "get", "msg_1")
        self.assertEqual(r.returncode, 3)
        self.assertIn(path, r.stderr)


class ScanTest(StateCase):
    def scan(self, *args, stdin=""):
        return subprocess.run(
            [sys.executable, "-I", STATE, "scan", *args], input=stdin,
            env={**os.environ, "HOME": self.home}, capture_output=True, text=True,
        )

    def answer(self, seq):
        self.state("handled", "start", f"msg_{seq}", "--seq", str(seq), "--type", "question")
        self.state("handled", "answer", f"msg_{seq}")

    def pending_seqs(self, *rows, limit="100"):
        r = self.scan("pending", "--run", "run_a", "--limit", limit, stdin=inbox(*rows))
        return r, [x["sequence"] for x in json.loads(r.stdout)] if r.stdout.strip() else None

    def test_pending_refuses_unseeded(self):
        r = self.scan("pending", "--run", "run_a", "--limit", "100", stdin=inbox(row(11)))
        self.assertEqual((r.returncode, r.stdout), (3, ""))

    def test_seed_sets_max_then_refuses_second_seed(self):
        r = self.scan("seed", "--run", "run_a", stdin=inbox(row(12), row(10), row(99, to="run:other")))
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.scan("floor").stdout, "12\n")
        r = self.scan("seed", "--run", "run_a", stdin=inbox(row(20)))
        self.assertEqual(r.returncode, 3)
        self.assertEqual(self.scan("floor").stdout, "12\n")

    def test_floor_unseeded_exit3(self):
        self.assertEqual(self.scan("floor").returncode, 3)

    def test_pending_routes_consumed_once(self):
        self.scan("seed", "--run", "run_a", stdin=inbox(row(10)))
        r, seqs = self.pending_seqs(row(11), row(10))
        self.assertEqual((r.returncode, seqs), (0, [11]))
        self.answer(11)
        r, seqs = self.pending_seqs(row(11), row(10))
        self.assertEqual((r.returncode, seqs), (0, []))

    def test_pending_ignores_other_mailboxes(self):
        self.scan("seed", "--run", "run_a", stdin=inbox(row(10)))
        r, seqs = self.pending_seqs(row(12, to="run:other"), row(11), row(10))
        self.assertEqual(seqs, [11])

    def test_pending_oldest_first(self):
        self.scan("seed", "--run", "run_a", stdin=inbox(row(10)))
        r, seqs = self.pending_seqs(row(13), row(12), row(10))
        self.assertEqual(seqs, [12, 13])

    def test_advance_stops_at_first_unanswered(self):
        self.scan("seed", "--run", "run_a", stdin=inbox(row(10)))
        self.answer(11)
        self.state("handled", "start", "msg_12", "--seq", "12", "--type", "question")
        self.answer(13)
        r = self.scan("advance", "--run", "run_a", "--limit", "100", stdin=inbox(row(13), row(12), row(11), row(10)))
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.scan("floor").stdout, "11\n")
        ids = [json.loads(x)["msg_id"] for x in self.read(os.path.join(self.root, "handled.jsonl")).splitlines()]
        self.assertNotIn("msg_11", ids)
        self.assertIn("msg_12", ids)
        self.assertIn("msg_13", ids)

    def test_window_short_exit5(self):
        self.scan("seed", "--run", "run_a", stdin=inbox(row(10)))
        r, seqs = self.pending_seqs(row(21), row(20), limit="2")
        self.assertEqual(r.returncode, 5)
        self.assertIn("window short", r.stderr)
        self.assertEqual(seqs, [20, 21])

    def test_pending_refuses_other_run(self):
        self.scan("seed", "--run", "run_a", stdin=inbox(row(10)))
        r = self.scan("pending", "--run", "run_b", "--limit", "100", stdin=inbox(row(11, to="run:run_b")))
        self.assertEqual((r.returncode, r.stdout), (3, ""))
        self.assertTrue(r.stderr)

    def test_advance_refuses_other_run(self):
        self.scan("seed", "--run", "run_a", stdin=inbox(row(10)))
        r = self.scan("advance", "--run", "run_b", "--limit", "100", stdin=inbox(row(10)))
        self.assertEqual(r.returncode, 3)
        self.assertTrue(r.stderr)
        self.assertEqual(json.loads(self.read(os.path.join(self.root, "scan.json")))["run_id"], "run_a")

    def test_seed_new_run_overwrites(self):
        self.scan("seed", "--run", "run_a", stdin=inbox(row(10)))
        r = self.scan("seed", "--run", "run_b", stdin=inbox(row(30, to="run:run_b"), row(10)))
        self.assertEqual(r.returncode, 0)
        d = json.loads(self.read(os.path.join(self.root, "scan.json")))
        self.assertEqual((d["run_id"], d["floor"]), ("run_b", 30))

    def test_start_after_answered_refused(self):
        self.answer(11)
        before = self.read(os.path.join(self.root, "handled.jsonl"))
        r = self.state("handled", "start", "msg_11", "--seq", "11", "--type", "question")
        self.assertEqual(r.returncode, 3)
        self.assertEqual(self.read(os.path.join(self.root, "handled.jsonl")), before)
        self.assertEqual(self.state("handled", "get", "msg_11").stdout, "answered\n")

    def test_advance_window_short_keeps_floor(self):
        self.scan("seed", "--run", "run_a", stdin=inbox(row(10)))
        self.answer(20)
        self.answer(21)
        before = self.read(os.path.join(self.root, "handled.jsonl"))
        r = self.scan("advance", "--run", "run_a", "--limit", "2", stdin=inbox(row(21), row(20)))
        self.assertEqual(r.returncode, 5)
        self.assertIn("window short", r.stderr)
        self.assertEqual(self.scan("floor").stdout, "10\n")
        self.assertEqual(self.read(os.path.join(self.root, "handled.jsonl")), before)


if __name__ == "__main__":
    unittest.main()
