"""Tests for watchdog.py. Run from the repo root: python3 -I scripts/watchdog_test.py -v

decide() is pure and tested as a table. CLI tests run watchdog.py with HOME in a temp
folder and a fake `orca` first on PATH that logs its argv and returns canned JSON.
"""
import json, os, plistlib, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
WATCHDOG = os.path.join(HERE, "watchdog.py")
sys.path.insert(0, HERE)
import watchdog  # noqa: E402

MIN = 60_000
NOW = 100 * MIN


def obs(**kw):
    base = {"saved_terminal": "term_a", "live_handles": {"term_a"}, "bound_run": "run_1",
            "shared_run": "run_1", "screen": "", "heartbeat_ms": NOW - MIN,
            "last_launch_ms": None, "failures": 0, "paused": False}
    base.update(kw)
    return base


class DecideTest(unittest.TestCase):
    def test_decide_paused(self):
        self.assertEqual(watchdog.decide(obs(paused=True, live_handles=set()), NOW)[0], "paused")

    def test_decide_unknown_handles_never_launches(self):
        self.assertEqual(watchdog.decide(obs(live_handles=None), NOW), ("notice", "orca not answering"))
        self.assertEqual(watchdog.decide(obs(live_handles=None, saved_terminal=None), NOW)[0], "notice")

    def test_decide_missing_terminal_launches(self):
        self.assertEqual(watchdog.decide(obs(live_handles={"term_b"}), NOW)[0], "launch")
        self.assertEqual(watchdog.decide(obs(saved_terminal=None), NOW)[0], "launch")

    def test_decide_lock_blocks_relaunch(self):
        self.assertEqual(watchdog.decide(obs(live_handles=set(), last_launch_ms=NOW - 9 * MIN), NOW)[0], "locked")
        self.assertEqual(watchdog.decide(obs(live_handles=set(), last_launch_ms=NOW - 10 * MIN), NOW)[0], "launch")

    def test_decide_fenced(self):
        self.assertEqual(watchdog.decide(obs(bound_run=None), NOW), ("notice", "fenced"))

    def test_decide_permission_prompt(self):
        for s in ("x\nDo you want to proceed?\n", "Do you want to create foo.py?"):
            self.assertEqual(watchdog.decide(obs(screen=s), NOW), ("notice", "permission prompt"))

    def test_decide_not_waiting(self):
        self.assertEqual(watchdog.decide(obs(heartbeat_ms=None), NOW), ("notice", "not waiting"))
        self.assertEqual(watchdog.decide(obs(heartbeat_ms=NOW - 21 * MIN), NOW), ("notice", "not waiting"))

    def test_decide_ok(self):
        self.assertEqual(watchdog.decide(obs(), NOW)[0], "ok")


class FailuresTest(unittest.TestCase):
    def test_failures_pause_after_two(self):
        wd = {"last_launch_ms": NOW - 5 * MIN, "failures": 0, "paused": False, "last_notice": ""}
        watchdog.count_failures(wd, None, NOW)
        self.assertEqual((wd["failures"], wd["last_launch_ms"], wd["paused"]), (1, NOW - 5 * MIN, False))
        wd["last_launch_ms"] = NOW - 6 * MIN
        watchdog.count_failures(wd, NOW - 7 * MIN, NOW)
        self.assertEqual((wd["failures"], wd["paused"]), (2, True))

    def test_lock_holds_and_launch_counted_once(self):
        t0 = NOW
        wd = {"last_launch_ms": t0, "failures": 0, "paused": False}
        gone = obs(live_handles=set(), heartbeat_ms=None)
        def step(t):
            watchdog.count_failures(wd, None, t)
            return watchdog.decide({**gone, "last_launch_ms": wd["last_launch_ms"],
                                    "failures": wd["failures"], "paused": wd["paused"]}, t)[0]
        self.assertEqual((step(t0 + 5 * MIN), wd["failures"]), ("locked", 1))
        self.assertEqual((step(t0 + 6 * MIN), wd["failures"]), ("locked", 1))
        self.assertEqual((step(t0 + 10 * MIN), wd["failures"]), ("launch", 1))

    def test_too_early_not_counted(self):
        wd = {"last_launch_ms": NOW - 4 * MIN, "failures": 0, "paused": False}
        watchdog.count_failures(wd, None, NOW)
        self.assertEqual((wd["failures"], wd["last_launch_ms"]), (0, NOW - 4 * MIN))

    def test_fresh_heartbeat_resets(self):
        wd = {"last_launch_ms": NOW - 3 * MIN, "failures": 1, "paused": False}
        watchdog.count_failures(wd, NOW - MIN, NOW)
        self.assertEqual(wd["failures"], 0)


FAKE = r'''#!/usr/bin/env python3
import json, os, sys
d = os.environ["FAKE_DIR"]
with open(os.path.join(d, "argv.log"), "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\n")
a = sys.argv[1:]
if a[:2] == ["orchestration", "run-current"] and os.path.exists(os.path.join(d, "rc_fail")):
    sys.exit(1)
if a[:1] == ["status"]:
    sys.exit(int(open(os.path.join(d, "status_rc")).read()))
canned = {"open": {"ok": True},
          "terminal list": {"result": {"terminals": [{"handle": h, "title": ""} for h in open(os.path.join(d, "handles")).read().split()],
                                       "truncated": os.path.exists(os.path.join(d, "truncated"))}},
          "orchestration run-current": {"ok": True, "result": {"runId": "run_1"}},
          "terminal read": {"result": {"terminal": {"tail": ["idle"]}}},
          "agent launch": {"ok": True, "result": {"terminal": {"handle": "term_new"}}}}
print(json.dumps(canned.get(" ".join(a[:2]), {})))
'''


class RunCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = self._tmp.name
        self.root = os.path.join(self.home, ".claude", "pipeline")
        self.bin = os.path.join(self.home, "bin")
        os.makedirs(self.bin)
        os.makedirs(self.root)
        p = os.path.join(self.bin, "orca")
        with open(p, "w") as f:
            f.write(FAKE.replace("/usr/bin/env python3", sys.executable))
        os.chmod(p, 0o755)
        self.set("status_rc", "0")
        self.set("handles", "term_a")
        self.wjson("coordinator.json", {"run_id": "run_1", "terminal": "term_a"})

    def tearDown(self):
        self._tmp.cleanup()

    def set(self, name, text):
        with open(os.path.join(self.home, name), "w") as f:
            f.write(text)

    def wjson(self, name, data):
        with open(os.path.join(self.root, name), "w") as f:
            json.dump(data, f)

    def rjson(self, name):
        with open(os.path.join(self.root, name)) as f:
            return json.load(f)

    def argv(self):
        p = os.path.join(self.home, "argv.log")
        if not os.path.exists(p):
            return []
        with open(p) as f:
            return [json.loads(l) for l in f]

    def notices(self):
        p = os.path.join(self.root, "notices.jsonl")
        if not os.path.exists(p):
            return []
        with open(p) as f:
            return [json.loads(l) for l in f if l.strip()]

    def wd(self, *args):
        env = {**os.environ, "HOME": self.home, "FAKE_DIR": self.home,
               "PATH": self.bin + os.pathsep + os.environ.get("PATH", "")}
        return subprocess.run([sys.executable, "-I", WATCHDOG, *args], env=env,
                              capture_output=True, text=True)

    def test_run_opens_orca_when_status_fails(self):
        self.set("status_rc", "1")
        r = self.wd("run", "--workspace", "/ws")
        self.assertEqual(r.returncode, 0, r.stderr)
        cmds = [a[:1] for a in self.argv()]
        self.assertIn(["open"], cmds)
        self.assertEqual(cmds.count(["open"]), 1)

    def test_run_launches_when_terminal_gone(self):
        self.set("handles", "term_b")
        r = self.wd("run", "--workspace", "/ws")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(["agent", "launch", "--agent", "claude", "--surface", "terminal",
                       "--worktree", "path:/ws", "--prompt", "/pipeline", "--json"], self.argv())
        self.assertIsNotNone(self.rjson("watchdog.json")["last_launch_ms"])

    def test_notice_not_repeated(self):
        # terminal alive, no heartbeat -> "not waiting" notice, once
        for _ in range(3):
            r = self.wd("run", "--workspace", "/ws")
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.notices()), 1)
        self.assertFalse(any(a[:2] == ["agent", "launch"] for a in self.argv()))

    def test_run_current_failure_is_not_fenced(self):
        import time
        self.set("rc_fail", "1")
        self.wjson("heartbeat", {"at": int(time.time() * 1000), "iso": "", "terminal": "term_a"})
        r = self.wd("run", "--workspace", "/ws")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "ok"), r.stderr)
        self.assertEqual(self.notices(), [])

    def test_launch_saves_new_terminal(self):
        self.wjson("coordinator.json", {"run_id": "run_1", "terminal": "term_a", "created": "c"})
        self.set("handles", "term_b")
        self.assertEqual(self.wd("run", "--workspace", "/ws").returncode, 0)
        c = self.rjson("coordinator.json")
        self.assertEqual((c["terminal"], c["run_id"], c["created"]), ("term_new", "run_1", "c"))

    def test_terminal_list_asks_1000(self):
        self.wd("run", "--workspace", "/ws")
        self.assertIn(["terminal", "list", "--limit", "1000", "--json"], self.argv())

    def test_truncated_list_is_unknown_never_launch(self):
        self.set("handles", "term_b")
        self.set("truncated", "1")
        r = self.wd("run", "--workspace", "/ws")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(any(a[:2] == ["agent", "launch"] for a in self.argv()))
        self.assertEqual([n["line"] for n in self.notices()], ["coordinator: orca not answering"])

    def test_launch_without_coord_file_writes_no_coord(self):
        os.remove(os.path.join(self.root, "coordinator.json"))
        self.assertEqual(self.wd("run", "--workspace", "/ws").returncode, 0)
        self.assertTrue(any(a[:2] == ["agent", "launch"] for a in self.argv()))
        self.assertFalse(os.path.exists(os.path.join(self.root, "coordinator.json")))

    def test_launch_with_empty_run_id_keeps_coord(self):
        self.wjson("coordinator.json", {"run_id": "", "terminal": "term_a"})
        self.set("handles", "term_b")
        self.assertEqual(self.wd("run", "--workspace", "/ws").returncode, 0)
        self.assertEqual(self.rjson("coordinator.json"), {"run_id": "", "terminal": "term_a"})

    def test_bad_coord_is_notice_not_launch(self):
        with open(os.path.join(self.root, "coordinator.json"), "w") as f:
            f.write("{bad")
        r = self.wd("run", "--workspace", "/ws")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(any(a[:2] == ["agent", "launch"] for a in self.argv()))
        self.assertEqual(len(self.notices()), 1)

    def test_resume_clears(self):
        self.wjson("watchdog.json", {"last_launch_ms": None, "failures": 2, "paused": True, "last_notice": "x"})
        self.assertEqual(self.wd("resume").returncode, 0)
        wd = self.rjson("watchdog.json")
        self.assertEqual((wd["paused"], wd["failures"]), (False, 0))

    def test_plist_is_valid(self):
        r = self.wd("plist", "--workspace", "/ws")
        self.assertEqual(r.returncode, 0, r.stderr)
        p = plistlib.loads(r.stdout.encode())
        self.assertEqual(p["Label"], "com.mission-pipeline.coordinator-watchdog")
        self.assertEqual(p["StartInterval"], 60)
        self.assertIs(p["RunAtLoad"], True)
        self.assertEqual(p["ProgramArguments"], ["/usr/bin/python3", "-I", WATCHDOG, "run", "--workspace", "/ws"])
        self.assertEqual(p["StandardErrorPath"], os.path.join(self.home, ".claude", "pipeline", "watchdog.log"))
        self.assertIn("/Applications/Orca.app/Contents/Resources/bin", p["EnvironmentVariables"]["PATH"])


if __name__ == "__main__":
    unittest.main()
