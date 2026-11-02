"""Tests for coord.py. Run from the repo root: python3 -I scripts/coord_test.py -v

Each test runs coord.py as a CLI with HOME pointed at a temp folder and a fake
`orca` first on PATH. The fake prints a canned reply and logs its argv.
"""
import json, os, stat, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
COORD = os.path.join(HERE, "coord.py")
STATE = os.path.join(HERE, "state.py")
sys.path.insert(0, HERE)
import coord  # noqa: E402

FAKE = """#!{py}
import json, os, sys
with open(os.environ["FAKE_ORCA_LOG"], "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
with open(os.environ["FAKE_ORCA_OUT"]) as f:
    sys.stdout.write(f.read())
sys.exit(int(os.environ.get("FAKE_ORCA_EXIT", "0")))
"""


def inbox(*rows):
    return json.dumps({"ok": True, "result": {"messages": list(rows)}})


def row(seq, to="run:run_a"):
    return {"id": f"msg_{seq}", "sequence": seq, "to_handle": to, "type": "question",
            "from_handle": "term_x", "body": "b", "subject": "s", "created_at": "2026-11-02T11:42:58Z"}


class CoordCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = self._tmp.name
        self.root = os.path.join(self.home, ".claude", "pipeline")
        self.bin = os.path.join(self.home, "bin")
        os.makedirs(self.bin)
        fake = os.path.join(self.bin, "orca")
        with open(fake, "w") as f:
            f.write(FAKE.format(py=sys.executable))
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)
        self.log = os.path.join(self.home, "orca.log")
        self.out = os.path.join(self.home, "orca.out")
        self.reply(inbox())
        self.env = {**os.environ, "HOME": self.home, "PATH": self.bin + os.pathsep + os.environ["PATH"],
                    "FAKE_ORCA_LOG": self.log, "FAKE_ORCA_OUT": self.out, "ORCA_TERMINAL_HANDLE": "term_c"}

    def tearDown(self):
        self._tmp.cleanup()

    def reply(self, text):
        with open(self.out, "w") as f:
            f.write(text)

    def coord(self, *args, **extra):
        return subprocess.run([sys.executable, "-I", COORD, *args],
                              env={**self.env, **extra}, capture_output=True, text=True)

    def state(self, *args, stdin=""):
        return subprocess.run([sys.executable, "-I", STATE, *args], input=stdin,
                              env=self.env, capture_output=True, text=True)

    def read(self, path):
        with open(path) as f:
            return f.read()

    def calls(self):
        return [json.loads(l) for l in self.read(self.log).splitlines()]


class ArgvTest(unittest.TestCase):
    def test_inbox_argv_exact(self):
        self.assertEqual(coord.inbox_argv("R", 100),
                         ["orca", "orchestration", "inbox", "--terminal", "run:R", "--limit", "100", "--full", "--json"])

    def test_wait_argv_has_no_ack(self):
        a = coord.wait_argv("R")
        for x in ("--full", "--wait", "--timeout-ms", "900000"):
            self.assertIn(x, a)
        self.assertNotIn("--ack", a)
        self.assertEqual(a, ["orca", "orchestration", "check", "--run", "R", "--wait", "--types",
                             "worker_done,escalation,question", "--timeout-ms", "900000", "--full", "--json"])


class CliTest(CoordCase):
    def test_wait_writes_out_and_heartbeat(self):
        self.reply('{"ok":true,"result":{"messages":[]}}')
        out = os.path.join(self.home, "wait.json")
        r = self.coord("wait", "--run", "run_a", "--out", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read(out), '{"ok":true,"result":{"messages":[]}}')
        self.assertEqual(json.loads(self.read(os.path.join(self.root, "heartbeat")))["terminal"], "term_c")
        self.assertEqual(self.calls(), [coord.wait_argv("run_a")[1:]])

    def test_scan_prints_pending(self):
        self.state("scan", "seed", "--run", "run_a", stdin=inbox(row(10)))
        self.reply(inbox(row(12), row(11), row(10)))
        r = self.coord("scan", "--run", "run_a")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([x["sequence"] for x in json.loads(r.stdout)], [11, 12])
        self.assertEqual(self.calls(), [coord.inbox_argv("run_a", 100)[1:]])

    def test_scan_window_short_writes_notice_exit5(self):
        self.state("scan", "seed", "--run", "run_a", stdin=inbox(row(10)))
        self.reply(inbox(row(21), row(20)))
        r = self.coord("scan", "--run", "run_a", "--limit", "2")
        self.assertEqual(r.returncode, 5)
        notes = [json.loads(l) for l in self.read(os.path.join(self.root, "notices.jsonl")).splitlines()]
        self.assertEqual([n["kind"] for n in notes], ["scan"])

    def test_advance_window_short_exit5_floor_kept(self):
        self.state("scan", "seed", "--run", "run_a", stdin=inbox(row(10)))
        self.reply(inbox(row(21), row(20)))
        r = self.coord("advance", "--run", "run_a", "--limit", "2")
        self.assertEqual(r.returncode, 5)
        self.assertEqual(self.state("scan", "floor").stdout, "10\n")

    def test_seed_sets_floor(self):
        self.reply(inbox(row(7), row(9)))
        r = self.coord("seed", "--run", "run_a")
        self.assertEqual((r.returncode, r.stdout), (0, "9\n"))

    def test_scan_unseeded_exit3(self):
        self.reply(inbox(row(7)))
        self.assertEqual(self.coord("scan", "--run", "run_a").returncode, 3)

    def test_orca_error_passthrough(self):
        self.state("scan", "seed", "--run", "run_a", stdin=inbox(row(10)))
        self.reply('{"ok":false,"error":{"message":"boom"}}')
        r = self.coord("scan", "--run", "run_a", FAKE_ORCA_EXIT="1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("boom", r.stdout + r.stderr)
        self.assertEqual(self.state("scan", "floor").stdout, "10\n")


if __name__ == "__main__":
    unittest.main()
