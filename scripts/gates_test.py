"""Tests for gates.py. Run from the repo root: python3 -I scripts/gates_test.py -v

The read and verify gates run git, so each test gets a temp git repo. Nothing touches real
mission files.
"""
import json, os, subprocess, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I drops the script folder
import gates  # noqa: E402

SPEC = """# Spec

## Goal
g

## Design
d

## Requirement findings
- RQ-01: the owner picked the first reading

<!-- cases:start -->
### VC-01 The note shows
family: main
- [api] create a job
- [mobile] open the job
expected: the note is in the list

### VC-02 The server is down
family: error
- [mobile] save with no network
expected: a retry button shows

- no permission case: the screen has no right of its own
<!-- cases:end -->
"""
FINDINGS = "- RQ-01 | ambiguous | 'recent' has no number | none\n"
PLAN = """# Plan

<!-- case-tasks:start -->
VC-01: T1, T2
VC-02: T2
<!-- case-tasks:end -->

tier: mobile
"""


def codes(errs):
    return sorted({code for code, _ in errs})


class GateCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = os.path.realpath(self._tmp.name)
        self.repo = os.path.join(self.t, "repo")
        subprocess.run(["git", "init", "-q", "-b", "main", self.repo], check=True)
        for k, v in (("user.email", "t@t"), ("user.name", "t"), ("commit.gpgsign", "false")):
            subprocess.run(["git", "-C", self.repo, "config", k, v], check=True)
        self.write(os.path.join(self.repo, "lib/a.dart"), "one\ntwo\nthree\n")
        subprocess.run(["git", "-C", self.repo, "add", "."], check=True)
        subprocess.run(["git", "-C", self.repo, "commit", "-q", "-m", "init"], check=True)
        self.head = subprocess.run(["git", "-C", self.repo, "rev-parse", "HEAD"], capture_output=True,
                                   text=True).stdout.strip()
        self.files = os.path.join(self.t, "files")
        os.makedirs(self.files)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        return path

    def f(self, name, text):
        return self.write(os.path.join(self.files, name), text)


class ReadGateTest(GateCase):
    def read(self, text, findings=FINDINGS, repos=None):
        p = self.f("readings/ui.md", text)
        fp = os.path.join(self.files, "requirement-findings.md")
        if findings is not None:
            self.write(fp, findings)
        return gates.gate_read([p], repos or {"app": self.repo}, fp)

    def test_pass(self):
        self.assertEqual(self.read("It is here [app:lib/a.dart:2] and [app:lib/a.dart:1-3].\n\n## Could not verify\nnone\n"), [])

    def test_no_readings(self):
        self.assertEqual(codes(gates.gate_read([], {}, self.f("requirement-findings.md", ""))), ["READ-NO-READINGS"])

    def test_missing_file(self):
        errs = gates.gate_read([os.path.join(self.files, "nope.md")], {}, self.f("requirement-findings.md", ""))
        self.assertEqual(codes(errs), ["READ-FILE-MISSING"])

    def test_no_citation_and_no_unverified_section(self):
        self.assertEqual(codes(self.read("plain text\n")), ["READ-NO-CITATION", "READ-NO-UNVERIFIED"])

    def test_unknown_repo_key(self):
        self.assertEqual(codes(self.read("[web:lib/a.dart:1]\n## Could not verify\n")), ["READ-REPO-UNKNOWN"])

    def test_file_not_at_head(self):
        self.write(os.path.join(self.repo, "lib/new.dart"), "x\n")  # on disk, not committed
        self.assertEqual(codes(self.read("[app:lib/new.dart:1]\n## Could not verify\n")), ["READ-CITE-MISSING"])

    def test_line_past_the_end_and_a_bad_range(self):
        errs = self.read("[app:lib/a.dart:4] [app:lib/a.dart:2-9] [app:lib/a.dart:3-2] [app:lib/a.dart:0]\n## Could not verify\n")
        self.assertEqual([c for c, _ in errs], ["READ-CITE-LINE"] * 4)

    def test_other_brackets_are_not_citations(self):
        errs = self.read("[code: x] [1] [link](http://a) [app:lib/a.dart:1]\n## Could not verify\n")
        self.assertEqual(errs, [])

    def test_findings_file_missing(self):
        self.assertEqual(codes(self.read("[app:lib/a.dart:1]\n## Could not verify\n", findings=None)), ["READ-NO-FINDINGS"])

    def test_findings_bad_line_and_empty_file(self):
        ok = "[app:lib/a.dart:1]\n## Could not verify\n"
        self.assertEqual(codes(self.read(ok, findings="- RQ-01 | wrong type | s | none\n- RQ-02 | ambiguous\n")),
                         ["READ-FINDING-FORMAT"])
        self.assertEqual(self.read(ok, findings=""), [])


class SpecGateTest(GateCase):
    def spec(self, text=SPEC, findings=FINDINGS):
        fp = os.path.join(self.files, "requirement-findings.md")
        if findings is not None:
            self.write(fp, findings)
        return gates.gate_spec(self.f("spec.md", text), fp)

    def test_pass(self):
        self.assertEqual(self.spec(), [])

    def test_missing_file(self):
        self.assertEqual(codes(gates.gate_spec("", "")), ["SPEC-FILE-MISSING"])

    def test_missing_sections_and_no_cases(self):
        self.assertEqual(codes(self.spec("# Spec\n- RQ-01: ok\n")), ["SPEC-NO-CASES", "SPEC-SECTION-MISSING"])

    def test_case_errors(self):
        text = SPEC.replace("family: main", "family: big").replace("- [mobile] open the job", "- open the job") \
                   .replace("expected: a retry button shows\n", "").replace("### VC-02", "### VC-01")
        self.assertEqual(codes(self.spec(text)),
                         ["SPEC-CASE-DUP", "SPEC-CASE-EXPECTED", "SPEC-CASE-FAMILY", "SPEC-CASE-STEP"])

    def test_case_with_no_steps(self):
        text = SPEC.replace("- [api] create a job\n- [mobile] open the job\n", "")
        self.assertEqual(codes(self.spec(text)), ["SPEC-CASE-STEP"])

    def test_required_families(self):
        text = SPEC.replace("- no permission case: the screen has no right of its own\n", "") \
                   .replace("family: error", "family: main")
        self.assertEqual(codes(self.spec(text)), ["SPEC-NO-ERROR-CASE", "SPEC-NO-PERMISSION-CASE"])

    def test_finding_without_a_resolution(self):
        self.assertEqual(codes(self.spec(findings=FINDINGS + "- RQ-02 | contradicts | x | none\n")),
                         ["SPEC-FINDING-UNRESOLVED"])

    def test_findings_file_missing(self):
        self.assertEqual(codes(self.spec(findings=None)), ["SPEC-NO-FINDINGS"])

    def test_hash_changes_with_the_block_only(self):
        a = gates.cases_hash(gates.parse_cases(SPEC)[0])
        self.assertEqual(a, gates.cases_hash(gates.parse_cases(SPEC.replace("## Goal\ng", "## Goal\nother"))[0]))
        self.assertNotEqual(a, gates.cases_hash(gates.parse_cases(SPEC.replace("retry button", "retry link"))[0]))


class PlanGateTest(GateCase):
    def plan(self, text=PLAN, frozen=None, spec=SPEC):
        sp = self.f("spec.md", spec)
        if frozen is None:
            frozen = gates.cases_hash(gates.parse_cases(SPEC)[0])
        return gates.gate_plan(self.f("plan.md", text), sp, frozen)

    def test_pass_markdown_and_html(self):
        self.assertEqual(self.plan(), [])
        html = "<html><body><pre>\n<!-- case-tasks:start -->\nVC-01: T1<br>\n<b>VC-02</b>: T2\n<!-- case-tasks:end -->\n</pre>\n<p>tier: cross-app</p></body></html>"
        self.assertEqual(self.plan(html), [])

    def test_missing_file(self):
        self.assertEqual(codes(gates.gate_plan("", "", "")), ["PLAN-FILE-MISSING"])

    def test_no_block_and_no_tier(self):
        self.assertEqual(codes(self.plan("# Plan\n")), ["PLAN-NO-CASE-TASKS", "PLAN-NO-TIER"])

    def test_unmapped_unknown_and_bad_lines(self):
        text = PLAN.replace("VC-02: T2", "VC-09: T2\nVC-03 -> T1").replace("tier: mobile", "tier: phone")
        self.assertEqual(codes(self.plan(text)),
                         ["PLAN-CASE-TASK-FORMAT", "PLAN-CASE-UNKNOWN", "PLAN-CASE-UNMAPPED", "PLAN-TIER-INVALID"])

    def test_cases_changed_after_the_freeze(self):
        self.assertEqual(codes(self.plan(spec=SPEC.replace("retry button", "retry link"))), ["PLAN-CASES-CHANGED"])

    def test_not_frozen_yet_is_not_an_error(self):
        self.assertEqual(self.plan(frozen=""), [])


class VerifyGateTest(GateCase):
    def setUp(self):
        super().setUp()
        self.spec = self.f("spec.md", SPEC)
        self.frozen = gates.cases_hash(gates.parse_cases(SPEC)[0])
        self.f("evidence/vc01.json", "{}")
        self.f("evidence/vc02.png", "x")

    def report(self, **over):
        rows = [
            {"case": "VC-01", "result": "pass", "class": "", "baseline": "fail",
             "evidence": [{"kind": "server", "path": "evidence/vc01.json"}]},
            {"case": "VC-02", "result": "pass", "class": "", "baseline": "fail",
             "evidence": [{"kind": "screenshot", "path": os.path.join(self.files, "evidence/vc02.png")}]},
        ]
        return {"commit": self.head, "cases_hash": self.frozen, "verdict": "VERIFIED", "rows": rows, **over}

    def verify(self, report, defects=None):
        p = self.f("verify.json", report if isinstance(report, str) else json.dumps(report))
        dp = os.path.join(self.files, "found-defects.md")
        if defects is not None:
            self.write(dp, defects)
        return gates.gate_verify(p, self.spec, self.frozen, self.repo, dp, self.files)

    def test_pass(self):
        self.assertEqual(self.verify(self.report()), [])

    def test_no_report_and_bad_json(self):
        self.assertEqual(codes(gates.gate_verify(os.path.join(self.files, "no.json"), self.spec, "", "", "", self.files)),
                         ["VERIFY-NO-REPORT"])
        self.assertEqual(codes(self.verify("{")), ["VERIFY-BAD-JSON"])
        self.assertEqual(codes(self.verify('{"rows": [1]}')), ["VERIFY-BAD-JSON"])

    def test_stale_commit_and_changed_cases(self):
        errs = self.verify(self.report(commit="abc", cases_hash="old"))
        self.assertEqual(codes(errs), ["VERIFY-CASES-CHANGED", "VERIFY-COMMIT-STALE"])

    def test_a_failed_row_cannot_be_verified(self):
        r = self.report()
        r["rows"][1] = {"case": "VC-02", "result": "fail", "class": "bug-app", "baseline": "fail"}
        self.assertEqual(codes(self.verify(r)), ["VERIFY-VERDICT-MISMATCH"])
        self.assertEqual(self.verify({**r, "verdict": "FIX"}), [])

    def test_fix_needs_a_failure(self):
        self.assertEqual(codes(self.verify(self.report(verdict="FIX"))), ["VERIFY-VERDICT-MISMATCH"])

    def test_failed_row_needs_a_class(self):
        r = self.report(verdict="FIX")
        r["rows"][0] = {"case": "VC-01", "result": "fail", "class": "", "baseline": "fail"}
        self.assertEqual(codes(self.verify(r)), ["VERIFY-NO-CLASS"])

    def test_missing_unknown_and_duplicate_rows(self):
        r = self.report(verdict="BLOCKED")
        r["rows"] = [r["rows"][0], dict(r["rows"][0]), {**r["rows"][0], "case": "XX-1"}, {**r["rows"][0], "case": "DC-01"}]
        self.assertEqual(codes(self.verify(r)), ["VERIFY-CASE-DUP", "VERIFY-CASE-MISSING", "VERIFY-CASE-UNKNOWN"])

    def test_evidence_rules(self):
        r = self.report()
        r["rows"][0]["evidence"] = []
        r["rows"][1]["evidence"] = [{"kind": "photo", "path": "evidence/none.png"}]
        self.assertEqual(codes(self.verify(r)), ["VERIFY-EVIDENCE-KIND", "VERIFY-EVIDENCE-MISSING", "VERIFY-NO-EVIDENCE"])

    def test_invalid_result_baseline_and_verdict(self):
        r = self.report(verdict="DONE")
        r["rows"][0]["result"] = "ok"
        r["rows"][0]["baseline"] = "red"
        self.assertEqual(codes(self.verify(r)), ["VERIFY-BASELINE-INVALID", "VERIFY-RESULT-INVALID", "VERIFY-VERDICT-INVALID"])

    def test_not_run_is_not_verified(self):
        r = self.report()
        r["rows"][1] = {"case": "VC-02", "result": "not-run", "class": "", "baseline": "fail"}
        self.assertEqual(codes(self.verify(r)), ["VERIFY-VERDICT-MISMATCH"])
        self.assertEqual(self.verify({**r, "verdict": "BLOCKED"}), [])

    def test_flaky_counts_as_a_pass(self):
        r = self.report()
        r["rows"][1]["result"] = "flaky"
        self.assertEqual(self.verify(r), [])

    def test_a_case_that_never_failed_on_the_base_goes_to_the_user(self):
        r = self.report()
        r["rows"][0]["baseline"] = "pass"
        self.assertEqual(codes(self.verify(r)), ["VERIFY-VERDICT-MISMATCH"])
        self.assertEqual(self.verify({**r, "verdict": "NEEDS_USER"}), [])

    def test_a_regression_case_may_have_passed_on_the_base(self):
        self.spec = self.f("spec.md", SPEC.replace("family: error", "family: regression")
                           .replace("<!-- cases:end -->", "- no error case: none applies\n<!-- cases:end -->"))
        self.frozen = gates.cases_hash(gates.parse_cases(gates.read_text(self.spec))[0])
        r = self.report()
        r["rows"][1]["baseline"] = "pass"
        self.assertEqual(self.verify(r), [])

    def test_an_open_in_scope_defect_is_a_fix(self):
        open_row = "- FD-01 | lib/a.dart:2 | in scope | open | verifier | evidence/vc01.json\n"
        self.assertEqual(codes(self.verify(self.report(), defects=open_row)), ["VERIFY-VERDICT-MISMATCH"])
        self.assertEqual(self.verify(self.report(verdict="FIX"), defects=open_row), [])
        self.assertEqual(self.verify(self.report(), defects=open_row.replace("| open |", "| closed |")), [])
        self.assertEqual(self.verify(self.report(), defects=open_row.replace("in scope", "out of scope")), [])

    def test_bad_defect_line(self):
        self.assertEqual(codes(self.verify(self.report(), defects="- FD-01 | place | maybe | open | w | e\n")),
                         ["VERIFY-DEFECT-FORMAT"])


if __name__ == "__main__":
    unittest.main()
