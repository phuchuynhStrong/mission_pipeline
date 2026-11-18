#!/usr/bin/env python3
"""Scripted stage gates of the verification loop. No AI, and no write of any kind.

Each gate_<stage> function reads the files it is given (and `git` for the read and verify
gates) and returns a list of (code, message). An empty list is a pass. The codes are stable:
the pattern log uses them as keys. `mission_ops.py gate` is the only caller.

File formats (design 5.17):
  citation          [<repo key>:<path>:<line>] or [<repo key>:<path>:<from>-<to>]
  finding           - RQ-<nn> | <type> | <statement> | <citation or none>
  resolution        - RQ-<nn>: <resolution>                     (in the spec)
  cases block       <!-- cases:start --> ... <!-- cases:end -->  (in the spec)
    case            ### VC-<nn> <title> / family: <f> / - [<surface>] <step> / expected: <text>
    no-case reason  - no error case: <reason>   |   - no permission case: <reason>
  case-task block   <!-- case-tasks:start --> ... <!-- case-tasks:end -->, lines VC-<nn>: T<n>[, T<n>]
  tier              tier: <value>                               (in the plan)
  found defect      - FD-<nn> | <place> | <in scope|out of scope> | <open|closed> | <who> | <evidence>
  verify report     verify.json, see gate_verify
"""
import hashlib, json, os, re, subprocess

FINDING_TYPES = ("ambiguous", "contradicts", "not testable", "missing case", "already true", "blocked by")
FAMILIES = ("main", "error", "permission", "regression")
SURFACES = ("api", "web", "mobile")
TIERS = ("none", "api", "web", "mobile", "cross", "cross-app")
RESULTS = ("pass", "fail", "flaky", "not-run")
CLASSES = ("bug-app", "test-drift", "data", "flaky", "not-shipped")
EVIDENCE_KINDS = ("screen", "screenshot", "server", "second-account", "log")
BASELINES = ("fail", "pass", "none")
VERDICTS = ("VERIFIED", "FIX", "NEEDS_USER", "BLOCKED")
# Open decision 2 of the design: a case that passes now but never failed on the base.
NEVER_SHOWN_VERDICT = "NEEDS_USER"
SPEC_SECTIONS = ("Goal", "Design")

CITE = re.compile(r"\[([A-Za-z][A-Za-z0-9_.-]*):([^\]\s:]+):(\d+)(?:-(\d+))?\]")
LOOSE_CITE = re.compile(r"\[([A-Za-z][A-Za-z0-9_.-]*):[^\]\n]*\]")  # starts like a citation; must then be a full one
CASE_HEAD = re.compile(r"^### (VC-\d+)(?:\s+(.*))?$")
FINDING = re.compile(r"^- (RQ-\d+) \| ([^|]+?) \| (.+?) \| (.+)$")
RESOLUTION = re.compile(r"^- (RQ-\d+):\s*\S", re.M)
CASES = re.compile(r"<!-- cases:start -->\n(.*?)<!-- cases:end -->", re.S)
CASE_TASKS = re.compile(r"<!-- case-tasks:start -->\n(.*?)<!-- case-tasks:end -->", re.S)
CASE_TASK = re.compile(r"^(VC-\d+):\s*T\d+(?:\s*,\s*T\d+)*$")
DEFECT = re.compile(r"^- (FD-\d+) \| (.+?) \| (in scope|out of scope) \| (open|closed) \| (.+?) \| (.+)$")
TAG = re.compile(r"<(?!!--)[^>]*>")


def read_text(path):
    """The file's text, or None when the path is empty or cannot be read."""
    if not path:
        return None
    try:
        with open(path) as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


def lines_at_head(repo, path, cache):
    """Line count of the file <path> at the repo's HEAD, or None when HEAD holds no file there."""
    key = (repo, path)
    if key not in cache:
        kind = subprocess.run(["git", "-C", repo, "cat-file", "-t", f"HEAD:{path}"], capture_output=True, text=True)
        if kind.returncode != 0 or kind.stdout.strip() != "blob":  # a folder is a tree, not a file
            cache[key] = None
        else:
            r = subprocess.run(["git", "-C", repo, "show", f"HEAD:{path}"], capture_output=True)
            cache[key] = len(r.stdout.splitlines()) if r.returncode == 0 else None
    return cache[key]


def parse_findings(text):
    """(ids, bad lines) of a requirement findings file."""
    ids, bad = [], []
    for line in text.splitlines():
        if not line.startswith("- RQ-"):
            continue
        hit = FINDING.match(line)
        if hit and hit.group(2).strip() in FINDING_TYPES:
            ids.append(hit.group(1))
        else:
            bad.append(line)
    return ids, bad


def parse_cases(text):
    """(block text or None, cases, no-case reasons, bad heading lines) of a spec."""
    hit = CASES.search(text)
    if not hit:
        return None, [], set(), []
    block, cases, reasons, bad_heads, cur = hit.group(1), [], set(), [], None
    for line in block.splitlines():
        if line.startswith("### "):
            head = CASE_HEAD.match(line)
            if not head:  # e.g. `### VC-02a`: not a case; its lines must not join the case before it
                bad_heads.append(line)
                cur = None
                continue
            cur = {"id": head.group(1), "title": (head.group(2) or "").strip(), "family": "", "steps": [],
                   "bad_steps": [], "expected": ""}
            cases.append(cur)
            continue
        reason = re.match(r"^- no (error|permission) case:\s*\S", line)
        if reason:
            reasons.add(reason.group(1))
            continue
        if cur is None:
            continue
        family = re.match(r"^family:\s*(.*)$", line)
        if family:
            cur["family"] = family.group(1).strip()
            continue
        expected = re.match(r"^expected:\s*(.*)$", line)
        if expected:
            cur["expected"] = expected.group(1).strip()
            continue
        step = re.match(r"^- \[([^\]]*)\]\s*(.*)$", line)
        if step and step.group(1) in SURFACES and step.group(2).strip():
            cur["steps"].append(line)
        elif line.startswith("- "):
            cur["bad_steps"].append(line)
    return block, cases, reasons, bad_heads


def cases_hash(block):
    return hashlib.sha256(block.encode()).hexdigest()


def parse_defects(text):
    """(rows, bad lines) of a found-defects file."""
    rows, bad = [], []
    for line in text.splitlines():
        if not line.startswith("- FD-"):
            continue
        hit = DEFECT.match(line)
        if hit:
            rows.append({"id": hit.group(1), "place": hit.group(2), "scope": hit.group(3), "status": hit.group(4)})
        else:
            bad.append(line)
    return rows, bad


def gate_read(paths, repos, findings_path):
    errs, cache = [], {}
    if not paths:
        errs.append(("READ-NO-READINGS", "the mission has no readings file"))
    for p in paths:
        text = read_text(p)
        if text is None:
            errs.append(("READ-FILE-MISSING", f"{p}: cannot be read"))
            continue
        if not re.search(r"^## Could not verify\s*$", text, re.M):
            errs.append(("READ-NO-UNVERIFIED", f"{p}: no heading '## Could not verify'"))
        cites = {c.group(0): c.groups() for c in CITE.finditer(text)}
        for loose in LOOSE_CITE.finditer(text):
            if loose.group(1) in repos and loose.group(0) not in cites:
                errs.append(("READ-CITE-FORMAT", f"{p}: {loose.group(0)}: want [<repo>:<path>:<line>] or [<repo>:<path>:<from>-<to>]"))
        if not cites:
            errs.append(("READ-NO-CITATION", f"{p}: no [repo:path:line] citation"))
        for tag, (key, path, first, last) in cites.items():
            if key not in repos:
                errs.append(("READ-REPO-UNKNOWN", f"{p}: {tag}: repo key '{key}' is not one of {sorted(repos)}"))
                continue
            count = lines_at_head(repos[key], path, cache)
            if count is None:
                errs.append(("READ-CITE-MISSING", f"{p}: {tag}: no such file at HEAD of {key}"))
            elif int(first) < 1 or int(last or first) < int(first) or int(last or first) > count:
                errs.append(("READ-CITE-LINE", f"{p}: {tag}: the file has {count} lines"))
    text = read_text(findings_path)
    if text is None:
        errs.append(("READ-NO-FINDINGS", f"{findings_path}: the requirement findings file is missing"))
    else:
        for line in parse_findings(text)[1]:
            errs.append(("READ-FINDING-FORMAT", f"bad finding line: {line}"))
    return errs


def gate_spec(spec_path, findings_path):
    text = read_text(spec_path)
    if text is None:
        return [("SPEC-FILE-MISSING", f"{spec_path}: cannot be read")]
    errs = []
    for name in SPEC_SECTIONS:
        if not re.search(rf"^## {name}\b", text, re.M):
            errs.append(("SPEC-SECTION-MISSING", f"no section '## {name}'"))
    block, cases, reasons, bad_heads = parse_cases(text)
    if not cases:
        errs.append(("SPEC-NO-CASES", "no case between <!-- cases:start --> and <!-- cases:end -->"))
    for line in bad_heads:
        errs.append(("SPEC-CASE-HEADING", f"bad case heading, want '### VC-<nn> <title>': {line}"))
    seen = set()
    for c in cases:
        if c["id"] in seen:
            errs.append(("SPEC-CASE-DUP", f"{c['id']}: the id is used twice"))
        seen.add(c["id"])
        if c["family"] not in FAMILIES:
            errs.append(("SPEC-CASE-FAMILY", f"{c['id']}: family '{c['family']}' is not one of {list(FAMILIES)}"))
        if not c["steps"]:
            errs.append(("SPEC-CASE-STEP", f"{c['id']}: no step line '- [<surface>] <step>'"))
        for line in c["bad_steps"]:
            errs.append(("SPEC-CASE-STEP", f"{c['id']}: a step needs a surface {list(SURFACES)}: {line}"))
        if not c["expected"]:
            errs.append(("SPEC-CASE-EXPECTED", f"{c['id']}: no 'expected:' line"))
    if cases:
        for family in ("error", "permission"):
            if family not in reasons and not any(c["family"] == family for c in cases):
                errs.append((f"SPEC-NO-{family.upper()}-CASE",
                             f"no {family} case and no line '- no {family} case: <reason>'"))
    findings = read_text(findings_path)
    if findings is None:
        errs.append(("SPEC-NO-FINDINGS", f"{findings_path}: the requirement findings file is missing"))
    else:
        resolved = set(RESOLUTION.findall(text))
        for rid in parse_findings(findings)[0]:
            if rid not in resolved:
                errs.append(("SPEC-FINDING-UNRESOLVED", f"{rid}: no resolution line '- {rid}: <resolution>'"))
    return errs


def gate_plan(plan_path, spec_path, frozen_hash):
    text = read_text(plan_path)
    if text is None:
        return [("PLAN-FILE-MISSING", f"{plan_path}: cannot be read")]
    errs = []
    block, cases = parse_cases(read_text(spec_path) or "")[:2]
    if not cases:
        errs.append(("PLAN-NO-CASES", "the spec has no case"))
    if not frozen_hash:
        errs.append(("PLAN-NOT-FROZEN", "the cases are not frozen yet: run freeze-cases after the spec gate"))
    elif block is None or cases_hash(block) != frozen_hash:
        errs.append(("PLAN-CASES-CHANGED", "the cases block of the spec changed after it was frozen"))
    plain = "\n".join(TAG.sub("", line) for line in text.splitlines())  # an HTML plan: tags off, comments kept
    hit = CASE_TASKS.search(plain)
    mapped = set()
    if not hit:
        errs.append(("PLAN-NO-CASE-TASKS", "no block between <!-- case-tasks:start --> and <!-- case-tasks:end -->"))
    else:
        for line in (l.strip() for l in hit.group(1).splitlines()):
            if not line:
                continue
            row = CASE_TASK.match(line)
            if row:
                mapped.add(row.group(1))
            else:
                errs.append(("PLAN-CASE-TASK-FORMAT", f"bad line, want 'VC-<nn>: T<n>[, T<n>]': {line}"))
        ids = [c["id"] for c in cases]
        for cid in ids:
            if cid not in mapped:
                errs.append(("PLAN-CASE-UNMAPPED", f"{cid}: no task"))
        for cid in sorted(mapped - set(ids)):
            errs.append(("PLAN-CASE-UNKNOWN", f"{cid}: not a case of the spec"))
    tier = re.search(r"^\s*tier:\s*(\S+)\s*$", plain, re.M)
    if not tier:
        errs.append(("PLAN-NO-TIER", "no line 'tier: <value>'"))
    elif tier.group(1) not in TIERS:
        errs.append(("PLAN-TIER-INVALID", f"tier '{tier.group(1)}' is not one of {list(TIERS)}"))
    return errs


def computed_verdict(rows, cases, defects):
    """The verdict the rows give (design 5.15.1). The verifier's own word must not be better than this."""
    by = {r.get("case"): r for r in rows if isinstance(r, dict)}
    if any(r.get("result") == "fail" for r in by.values()):
        return "FIX"
    if any(d["scope"] == "in scope" and d["status"] == "open" for d in defects):
        return "FIX"
    if any(r.get("result") == "not-run" for r in by.values()) or any(c["id"] not in by for c in cases):
        return "BLOCKED"
    for c in cases:
        if c["family"] != "regression" and by[c["id"]].get("baseline") != "fail":
            return NEVER_SHOWN_VERDICT
    return "VERIFIED"


def gate_verify(report_path, spec_path, frozen_hash, worktree, defects_path, files_dir):
    """verify.json: {"commit", "cases_hash", "verdict", "rows": [{"case", "result", "class",
    "baseline", "evidence": [{"kind", "path"}]}]}. A relative evidence path is under files_dir."""
    raw = read_text(report_path)
    if raw is None:
        return [("VERIFY-NO-REPORT", f"{report_path}: cannot be read")]
    try:
        report = json.loads(raw)
        rows = report["rows"]
        if not isinstance(report, dict) or not isinstance(rows, list) or not all(
                isinstance(r, dict) and isinstance(r.get("case"), str) for r in rows):
            raise ValueError("rows")
    except (ValueError, KeyError, TypeError):
        return [("VERIFY-BAD-JSON", f"{report_path}: want an object with a list 'rows' of objects, each with a string 'case'")]
    errs = []
    block, cases = parse_cases(read_text(spec_path) or "")[:2]
    if not cases:
        errs.append(("VERIFY-NO-CASES", "the spec has no case"))
    if not frozen_hash:
        errs.append(("VERIFY-NOT-FROZEN", "the cases are not frozen: run freeze-cases after the spec gate"))
    else:
        if block is None or cases_hash(block) != frozen_hash:
            errs.append(("VERIFY-CASES-CHANGED", "the cases block of the spec changed after it was frozen"))
        if report.get("cases_hash") != frozen_hash:
            errs.append(("VERIFY-CASES-CHANGED", "the report's cases_hash is not the frozen one"))
    root = os.path.realpath(files_dir)
    if worktree:
        head = subprocess.run(["git", "-C", worktree, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        if not head or report.get("commit") != head:
            errs.append(("VERIFY-COMMIT-STALE", f"the report is for commit {report.get('commit')}, HEAD is {head or 'unknown'}"))
    ids, seen = [c["id"] for c in cases], set()
    for r in rows:
        cid = r.get("case")
        if cid in seen:
            errs.append(("VERIFY-CASE-DUP", f"{cid}: two rows"))
        seen.add(cid)
        if cid not in ids and not re.match(r"^DC-\d+$", str(cid)):
            errs.append(("VERIFY-CASE-UNKNOWN", f"{cid}: not a case of the spec and not a diff case DC-<nn>"))
        result = r.get("result")
        if result not in RESULTS:
            errs.append(("VERIFY-RESULT-INVALID", f"{cid}: result '{result}' is not one of {list(RESULTS)}"))
        if r.get("baseline") not in BASELINES:
            errs.append(("VERIFY-BASELINE-INVALID", f"{cid}: baseline '{r.get('baseline')}' is not one of {list(BASELINES)}"))
        if result == "fail" and r.get("class") not in CLASSES:
            errs.append(("VERIFY-NO-CLASS", f"{cid}: a failed case needs a class {list(CLASSES)}"))
        if result in ("pass", "flaky"):
            evidence = r.get("evidence")
            if not isinstance(evidence, list) or not evidence:
                errs.append(("VERIFY-NO-EVIDENCE", f"{cid}: a passed case needs evidence"))
                continue
            for e in evidence:
                kind, path = (e.get("kind"), e.get("path")) if isinstance(e, dict) else (None, None)
                if kind not in EVIDENCE_KINDS:
                    errs.append(("VERIFY-EVIDENCE-KIND", f"{cid}: evidence kind '{kind}' is not one of {list(EVIDENCE_KINDS)}"))
                real = os.path.realpath(os.path.join(root, path)) if isinstance(path, str) and path else ""
                if not real.startswith(root + os.sep) or not os.path.isfile(real):
                    errs.append(("VERIFY-EVIDENCE-MISSING", f"{cid}: evidence {path} is not a file under the mission's files folder"))
    for cid in ids:
        if cid not in seen:
            errs.append(("VERIFY-CASE-MISSING", f"{cid}: no row"))
    defects, bad = parse_defects(read_text(defects_path) or "")
    for line in bad:
        errs.append(("VERIFY-DEFECT-FORMAT", f"bad found-defects line: {line}"))
    word, computed = report.get("verdict"), computed_verdict(rows, cases, defects)
    if word not in VERDICTS:
        errs.append(("VERIFY-VERDICT-INVALID", f"verdict '{word}' is not one of {list(VERDICTS)}"))
    elif (word in ("VERIFIED", "FIX") and word != computed) or (word == "BLOCKED" and computed == "FIX"):
        # NEEDS_USER is always allowed: a case that looks wrong is the owner's call, whatever the rows say
        errs.append(("VERIFY-VERDICT-MISMATCH", f"the report says {word}, the rows give {computed}"))
    return errs
