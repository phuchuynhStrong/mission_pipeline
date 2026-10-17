"""Tests for search_stats.py. Run from the repo root: python3 -I scripts/search_stats_test.py -v

The classifier tests call the functions directly. The CLI test writes fake
transcripts to a temp folder and runs the script with --root pointed at it.
"""
import importlib.util, json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "search_stats.py")
_spec = importlib.util.spec_from_file_location("search_stats", SCRIPT)
ss = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ss)


class BashSearchTest(unittest.TestCase):
    def test_search_programs_count(self):
        for cmd in ("grep -rn foo lib", "rg -t dart foo", "find . -name '*.dart'",
                    "git grep foo", "ag foo", "/usr/bin/grep foo x"):
            self.assertTrue(ss.is_bash_search(cmd), cmd)

    def test_grep_after_a_pipe_is_a_filter(self):
        self.assertFalse(ss.is_bash_search("flutter analyze 2>&1 | grep 'error •'"))
        self.assertFalse(ss.is_bash_search("git log --oneline | grep fix"))

    def test_search_after_cd_or_env_counts(self):
        self.assertTrue(ss.is_bash_search("cd apps/field_app_v2 && grep -rn foo lib"))
        self.assertTrue(ss.is_bash_search("LC_ALL=C grep foo x"))
        self.assertTrue(ss.is_bash_search("(cd lib; rg foo)"))

    def test_non_search_commands(self):
        for cmd in ("flutter analyze", "git status", "sed -n '1,20p' a.dart", "", None):
            self.assertFalse(ss.is_bash_search(cmd), cmd)


class LangTest(unittest.TestCase):
    def test_dart(self):
        self.assertEqual(ss.langs_of("lib/a.dart"), {"dart"})
        self.assertEqual(ss.langs_of("rg -t dart foo"), {"dart"})
        self.assertEqual(ss.langs_of("grep --include=*.dart foo"), {"dart"})

    def test_typescript(self):
        self.assertEqual(ss.langs_of("src/a.tsx"), {"ts"})
        self.assertEqual(ss.langs_of("rg --type=ts foo"), {"ts"})

    def test_lookalikes_are_not_typescript(self):
        self.assertEqual(ss.langs_of("results.tsv posts/"), {"unknown"})

    def test_both_and_none(self):
        self.assertEqual(ss.langs_of("a.dart b.ts"), {"dart", "ts"})
        self.assertEqual(ss.langs_of("grep -rn foo lib"), {"unknown"})
        self.assertEqual(ss.langs_of(None), {"unknown"})


class ClassifyTest(unittest.TestCase):
    def test_lsp(self):
        self.assertEqual(ss.classify("LSP", {"filePath": "/r/lib/a.dart"}), ("lsp", {"dart"}))

    def test_grep_tool_uses_path_glob_type_not_pattern(self):
        self.assertEqual(ss.classify("Grep", {"pattern": "x.dart", "path": "src"}),
                         ("grep", {"unknown"}))
        self.assertEqual(ss.classify("Grep", {"pattern": "x", "type": "dart"}),
                         ("grep", {"dart"}))

    def test_glob_tool(self):
        self.assertEqual(ss.classify("Glob", {"pattern": "**/*.ts"}), ("glob", {"ts"}))

    def test_not_searches(self):
        self.assertIsNone(ss.classify("Read", {"file_path": "a.dart"}))
        self.assertIsNone(ss.classify("Bash", {"command": "flutter analyze"}))
        self.assertIsNone(ss.classify("Edit", None))


class CliTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def transcript(self, rel, first_user, calls, ts="2026-10-17T10:00:00Z", extra=()):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        lines = [{"type": "user", "message": {"content": first_user}}]
        for i, (name, inp) in enumerate(calls):
            lines.append({"type": "assistant", "timestamp": ts, "message": {
                "content": [{"type": "tool_use", "id": f"{rel}-{i}", "name": name, "input": inp}]}})
        lines.extend(extra)
        with open(path, "w") as f:
            f.write("\n".join(json.dumps(x) for x in lines) + "\n")

    def run_json(self, *args, tz="UTC"):
        r = subprocess.run([sys.executable, "-I", SCRIPT, "--root", self.root, "--json", *args],
                           env={**os.environ, "TZ": tz}, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_counts_by_kind_and_language(self):
        self.transcript("proj/main.jsonl", "hello", [
            ("LSP", {"filePath": "lib/a.dart"}),
            ("Bash", {"command": "grep -rn foo --include=*.dart lib"}),
            ("Bash", {"command": "flutter analyze | grep error"}),
            ("Read", {"file_path": "lib/a.dart"}),
        ])
        self.transcript("proj/worker.jsonl", "x You are a dispatched worker. y", [
            ("Grep", {"pattern": "foo", "glob": "*.ts"}),
        ])
        self.transcript("proj/s1/subagents/agent-1.jsonl", "task", [
            ("Glob", {"pattern": "**/*.dart"}),
        ])
        report = self.run_json()
        dart = {r["group"]: r for r in report["dart"]}
        self.assertEqual(dart["main"]["total"], 2)
        self.assertEqual(dart["main"]["lsp"], 1)
        self.assertEqual(dart["main"]["lsp_pct"], 50.0)
        self.assertEqual(dart["subagent"]["glob"], 1)
        ts = {r["group"]: r for r in report["ts"]}
        self.assertEqual(ts["worker"]["grep"], 1)
        all_total = sum(r["total"] for r in report["all"])
        self.assertEqual(all_total, 4)

    def test_since_filters_old_calls(self):
        self.transcript("proj/old.jsonl", "hi", [("LSP", {"filePath": "a.dart"})],
                        ts="2026-01-01T00:00:00Z")
        self.transcript("proj/new.jsonl", "hi", [("Grep", {"type": "dart"})])
        report = self.run_json("--since", "2026-10-01")
        self.assertEqual(sum(r["lsp"] for r in report["all"]), 0)
        self.assertEqual(sum(r["grep"] for r in report["all"]), 1)

    def test_request_blobs_and_repeated_ids_count_once(self):
        call = {"type": "tool_use", "id": "proj/a.jsonl-0", "name": "LSP",
                "input": {"filePath": "a.dart"}}
        self.transcript("proj/a.jsonl", "hi", [("LSP", {"filePath": "a.dart"})], extra=[
            {"type": "api-request-blob", "message": {"content": [call]}},
            {"type": "assistant", "timestamp": "2026-10-17T10:00:01Z",
             "message": {"content": [call]}},
        ])
        report = self.run_json()
        self.assertEqual(sum(r["lsp"] for r in report["all"]), 1)

    def test_since_uses_local_date(self):
        # 19:10 UTC on the 16th is 02:10 on the 17th at UTC+7.
        self.transcript("proj/a.jsonl", "hi", [("LSP", {"filePath": "a.dart"})],
                        ts="2026-10-16T19:10:00Z")
        self.assertEqual(sum(r["lsp"] for r in self.run_json(
            "--since", "2026-10-17", tz="Asia/Ho_Chi_Minh")["all"]), 1)
        self.assertEqual(sum(r["lsp"] for r in self.run_json(
            "--since", "2026-10-17", tz="UTC")["all"]), 0)

    def result(self, rel, i, text, is_error=False, ts="2026-10-17T10:00:05Z"):
        block = {"type": "tool_result", "tool_use_id": f"{rel}-{i}", "content": text}
        if is_error:
            block["is_error"] = True
        return {"type": "user", "timestamp": ts, "message": {"content": [block]}}

    def health(self, *args):
        r = subprocess.run([sys.executable, "-I", SCRIPT, "--root", self.root, "--health", *args],
                           env={**os.environ, "TZ": "UTC"}, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_health_counts_ok_and_error_results(self):
        rel = "proj/a.jsonl"
        self.transcript(rel, "hi", [
            ("LSP", {"filePath": "lib/a.dart"}),
            ("LSP", {"filePath": "lib/b.dart"}),
            ("LSP", {"filePath": "lib/c.dart"}),
            ("Bash", {"command": "grep -rn foo --include=*.dart lib"}),
        ], extra=[
            self.result(rel, 0, "Found 8 references"),
            self.result(rel, 1, "Error: request timed out", is_error=True),
            self.result(rel, 2, "Hover info at 2:7", ts="2026-10-17T10:00:09Z"),
        ])
        h = self.health("--since", "2026-10-17")
        self.assertEqual((h["lsp_ok"], h["lsp_err"]), (2, 1))
        self.assertTrue(h["last_ok"])
        self.assertEqual(h["last_error"], "Error: request timed out")
        self.assertEqual((h["dart_lsp"], h["dart_total"]), (3, 4))

    def test_health_reads_no_server_text_as_an_error(self):
        rel = "proj/a.jsonl"
        self.transcript(rel, "hi", [("LSP", {"filePath": "a.dart"})], extra=[
            self.result(rel, 0, "No LSP server available for file type .dart")])
        h = self.health("--since", "2026-10-17")
        self.assertEqual((h["lsp_ok"], h["lsp_err"], h["last_ok"]), (0, 1, False))

    def test_health_with_no_calls(self):
        self.transcript("proj/a.jsonl", "hi", [("Bash", {"command": "rg -t dart foo"})])
        h = self.health("--since", "2026-10-17")
        self.assertEqual((h["lsp_ok"], h["lsp_err"], h["last_at"], h["last_ok"]), (0, 0, None, None))
        self.assertEqual((h["dart_lsp"], h["dart_total"]), (0, 1))

    def test_since_skips_files_last_changed_before_it(self):
        self.transcript("proj/old.jsonl", "hi", [("LSP", {"filePath": "a.dart"})])
        old = os.path.join(self.root, "proj/old.jsonl")
        stamp = 1_700_000_000  # 2023-11-14
        os.utime(old, (stamp, stamp))
        report = self.run_json("--since", "2026-10-01")
        self.assertEqual(sum(r["lsp"] for r in report["all"]), 0)

    def test_week_grouping(self):
        self.transcript("proj/a.jsonl", "hi", [("LSP", {"filePath": "a.dart"})],
                        ts="2026-10-17T00:00:00Z")
        report = self.run_json("--by", "week")
        self.assertEqual(report["all"][0]["group"], "2026-W42")


if __name__ == "__main__":
    unittest.main()
