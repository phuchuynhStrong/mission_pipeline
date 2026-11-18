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


    def test_run_empty_terminal_exit3(self):
        self.state("run", "--set", "run_a")
        before = self.read(self.coord)
        self.assertEqual(self.state("run", "--terminal", "").returncode, 3)
        self.assertEqual(self.state("run", "--set", "run_b", "--terminal", "").returncode, 3)
        self.assertEqual(self.read(self.coord), before)


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

    def test_seed_floor_below_lowest_unread(self):
        rows = [row(n) for n in (14, 13, 12, 11, 10)]
        rows[2]["read"] = 0  # seq 12
        rows[0]["read"] = False  # seq 14
        r = self.scan("seed", "--run", "run_a", stdin=inbox(*rows, {**row(5, to="run:other"), "read": 0}))
        self.assertEqual((r.returncode, r.stdout), (0, "11\n"))

    def test_seed_all_read_takes_max(self):
        r = self.scan("seed", "--run", "run_a", stdin=inbox(row(14), row(10), row(12)))
        self.assertEqual(r.stdout, "14\n")

    def test_advance_prune_uses_inbox_sequence_not_line_seq(self):
        self.scan("seed", "--run", "run_a", stdin=inbox(row(10)))
        self.answer(11)
        # msg_15 was recorded with a wrong small --seq; its real row is at 15, above the new floor
        self.state("handled", "start", "msg_15", "--seq", "11", "--type", "question")
        self.state("handled", "answer", "msg_15")
        self.state("handled", "start", "msg_12", "--seq", "12", "--type", "question")
        r = self.scan("advance", "--run", "run_a", "--limit", "100",
                      stdin=inbox(row(15), row(12), row(11), row(10)))
        self.assertEqual((r.returncode, r.stdout), (0, "11\n"))
        ids = [json.loads(x)["msg_id"] for x in self.read(os.path.join(self.root, "handled.jsonl")).splitlines()]
        self.assertNotIn("msg_11", ids)
        self.assertIn("msg_15", ids)
        self.assertIn("msg_12", ids)

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

    def test_start_below_floor_refused(self):
        self.scan("seed", "--run", "run_a", stdin=inbox(row(10)))
        r = self.state("handled", "start", "msg_10", "--seq", "10", "--type", "question")
        self.assertEqual(r.returncode, 3)
        self.assertIn("below floor", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.root, "handled.jsonl")))
        self.assertEqual(self.state("handled", "start", "msg_11", "--seq", "11", "--type", "question").returncode, 0)

    def test_get_below_floor_answered(self):
        self.scan("seed", "--run", "run_a", stdin=inbox(row(10)))
        self.assertEqual(self.state("handled", "get", "msg_9", "--seq", "9").stdout, "answered\n")
        self.assertEqual(self.state("handled", "get", "msg_11", "--seq", "11").stdout, "none\n")
        self.assertEqual(self.state("handled", "get", "msg_9").stdout, "none\n")

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


class NoticeTest(StateCase):
    def test_notice_add_list_clear(self):
        r = self.state("notice", "add", "--kind", "warn", "--line", "hello", "--mission", "repo/m1")
        self.assertEqual(r.returncode, 0)
        nid = r.stdout.strip()
        self.assertRegex(nid, r"^n_\d+$")
        rows = [json.loads(x) for x in self.state("notice", "list").stdout.splitlines()]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["id"], rows[0]["kind"], rows[0]["mission"], rows[0]["line"], rows[0]["cleared"]),
                         (nid, "warn", "repo/m1", "hello", False))
        self.assertIn("at", rows[0])
        self.assertEqual(self.state("notice", "clear", nid).returncode, 0)
        self.assertEqual(self.state("notice", "list").stdout, "")
        last = json.loads(self.read(os.path.join(self.root, "notices.jsonl")).splitlines()[-1])
        self.assertEqual((last["id"], last["cleared"]), (nid, True))

    def test_notice_list_all_shows_cleared(self):
        a = self.state("notice", "add", "--kind", "k", "--line", "one").stdout.strip()
        b = self.state("notice", "add", "--kind", "k", "--line", "two").stdout.strip()
        self.assertNotEqual(a, b)
        self.state("notice", "clear", a)
        rows = [json.loads(x) for x in self.state("notice", "list", "--all").stdout.splitlines()]
        self.assertEqual({r["id"]: r["cleared"] for r in rows}, {a: True, b: False})
        self.state("notice", "clear", "--all")
        self.assertEqual(self.state("notice", "list").stdout, "")

    def test_notice_corrupt_exit3(self):
        self.write(os.path.join(self.root, "notices.jsonl"), "{not json\n")
        self.assertEqual(self.state("notice", "list").returncode, 3)


class NoteTest(StateCase):
    def test_note_show_empty_exit0(self):
        r = self.state("note", "show")
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_note_add_then_show(self):
        self.assertEqual(self.state("note", "add", "first thing").returncode, 0)
        self.state("note", "add", "second")
        lines = self.state("note", "show").stdout.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith("- ") and lines[0].endswith(" first thing"))
        self.assertTrue(lines[1].endswith(" second"))


class HeartbeatTest(StateCase):
    def test_heartbeat_fields(self):
        self.assertEqual(self.state("heartbeat", "--terminal", "term_1").returncode, 0)
        d = json.loads(self.read(os.path.join(self.root, "heartbeat")))
        self.assertIsInstance(d["at"], int)
        self.assertGreater(d["at"], 10 ** 12)
        self.assertEqual(d["terminal"], "term_1")
        self.assertIn("iso", d)


class FileTest(StateCase):
    def test_file_write_and_dir(self):
        r = subprocess.run([sys.executable, "-I", STATE, "file", "write", "repo", "m1", "readings/ui.md"],
                           input="body\n", env={**os.environ, "HOME": self.home}, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        p = os.path.join(self.root, "files", "repo", "m1", "readings", "ui.md")
        self.assertEqual(r.stdout.strip(), p)
        self.assertEqual(self.read(p), "body\n")
        r = self.state("file", "dir", "repo", "m2")
        d = os.path.join(self.root, "files", "repo", "m2")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, d))
        self.assertTrue(os.path.isdir(d))

    def test_file_write_refuses_dotdot(self):
        for name in ("../x.md", "a/../../x.md", "/etc/x", "a/b/c.md"):
            r = self.state("file", "write", "repo", "m1", name)
            self.assertEqual(r.returncode, 3, name)
        self.assertFalse(os.path.exists(os.path.join(self.root, "files", "repo", "x.md")))

    def test_list_ignores_files_folder(self):
        self.mission("repo", "m1", dispatches=["ctx_a"], settled=[])
        self.write(os.path.join(self.root, "files", "repo", "m1", "pr.json"), json.dumps({"number": 1}))
        self.write(os.path.join(self.root, "files", "x.json"), "{not json")
        r = self.state("list")
        self.assertEqual((r.returncode, r.stdout.splitlines()), (0, ["repo/m1  stage=read  "]))
        r = self.state("owner", "ctx_a")
        self.assertEqual((r.returncode, r.stdout), (0, "repo m1 live\n"))



class VerificationLoopTest(StateCase):
    """Slice 1 of the verification loop: new stages, kind, file append, counters."""

    def new(self, *extra):
        return self.state("new", "app", "m1", "--run-id", "run_a", *extra)

    def load(self):
        return json.loads(self.read(os.path.join(self.root, "app", "m1.json")))

    def test_new_has_the_new_stages_skipped(self):
        self.assertEqual(self.new().returncode, 0)
        m = self.load()
        self.assertEqual([k for k in m["stages"]],
                         ["read", "scope", "spec", "plan", "preflight", "worktree", "build", "review", "verify", "pr"])
        for name in ("scope", "preflight", "verify"):
            self.assertEqual(m["stages"][name]["status"], "skipped")
        self.assertEqual((m["kind"], m["tier"], m["cases_hash"], m["counters"]), ("feature", "none", "", {}))

    def test_new_kind_bug(self):
        self.assertEqual(self.new("--kind", "bug").returncode, 0)
        self.assertEqual(self.load()["kind"], "bug")
        self.assertNotEqual(self.state("new", "app", "m2", "--run-id", "r", "--kind", "chore").returncode, 0)

    def test_abort_fails_an_active_new_stage_and_keeps_skipped(self):
        self.new()
        self.state("set", "app", "m1", "stages.verify.status=active")
        self.assertEqual(self.state("abort", "app", "m1").returncode, 0)
        m = self.load()
        self.assertEqual(m["stages"]["verify"]["status"], "failed")
        self.assertEqual(m["stages"]["scope"]["status"], "skipped")

    def test_abort_of_an_old_mission_without_the_new_stages(self):
        old = {"id": "m1", "stage": "build", "note": "", "events": [],
               "stages": {"build": {"status": "active"}}}
        self.write(os.path.join(self.root, "app", "m1.json"), json.dumps(old))
        self.assertEqual(self.state("abort", "app", "m1").returncode, 0)
        self.assertEqual(self.load()["stages"]["build"]["status"], "failed")

    def append(self, text, name="found-defects.md"):
        return subprocess.run([sys.executable, "-I", STATE, "file", "append", "app", "m1", name],
                              env={**os.environ, "HOME": self.home}, input=text, capture_output=True, text=True)

    def test_file_append_adds_rows_and_a_newline(self):
        self.assertEqual(self.append("- FD-01 | a").returncode, 0)
        r = self.append("- FD-02 | b\n")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.read(r.stdout.strip()), "- FD-01 | a\n- FD-02 | b\n")

    def test_file_append_refuses_a_bad_name(self):
        self.assertEqual(self.append("x", name="../x").returncode, 3)

    def test_file_append_in_parallel_loses_no_row(self):
        env = {**os.environ, "HOME": self.home}
        procs = [subprocess.Popen([sys.executable, "-I", STATE, "file", "append", "app", "m1", "rows.md"],
                                  env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) for _ in range(8)]
        for i, p in enumerate(procs):
            p.stdin.write(f"- row {i} " + "x" * 5000)
            p.stdin.close()
        for p in procs:
            self.assertEqual(p.wait(), 0)
            p.stdout.close()
        lines = self.read(os.path.join(self.root, "files", "app", "m1", "rows.md")).splitlines()
        self.assertEqual(sorted(l[:8] for l in lines), sorted(f"- row {i} " for i in range(8)))
        self.assertTrue(all(len(l) == 5008 for l in lines))

    def test_count_stops_over_the_limit(self):
        self.new()
        r = self.state("count", "app", "m1", "spec_returns")
        self.assertEqual((r.returncode, r.stdout), (0, "1 1\n"))
        r = self.state("count", "app", "m1", "spec_returns")
        self.assertEqual((r.returncode, r.stdout), (5, "2 1\n"))
        self.assertEqual(self.load()["counters"]["spec_returns"], 2)

    def test_count_gate_is_per_stage_and_round(self):
        self.new()
        self.assertEqual(self.state("count", "app", "m1", "gate:read:0").returncode, 0)
        self.assertEqual(self.state("count", "app", "m1", "gate:spec:0").returncode, 0)
        self.assertEqual(self.state("count", "app", "m1", "gate:read:0").returncode, 5)

    def test_count_without_a_limit_and_on_an_old_mission(self):
        self.write(os.path.join(self.root, "app", "m1.json"), json.dumps({"id": "m1", "stage": "build", "note": ""}))
        r = self.state("count", "app", "m1", "workers")
        self.assertEqual((r.returncode, r.stdout), (0, "1 -\n"))

if __name__ == "__main__":
    unittest.main()
