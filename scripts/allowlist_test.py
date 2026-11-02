"""Tests for coordinator_setup.py. Run from the repo root: python3 -I scripts/allowlist_test.py -v

Every command the skill docs tell the coordinator to run must match an allow rule of the
generated workspace settings: one unallowed command = a prompt nobody sees = a stalled coordinator.
"""
import os, re, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import coordinator_setup  # noqa: E402

ROOT = "/abs/plugin"
DOCS = [os.path.join(REPO, "skills", "pipeline", "SKILL.md"),
        os.path.join(REPO, "skills", "pipeline", "references", "orca-commands.md")]
CHECKED = ("orca ", "gh ", "python3 ", "pgrep ")
RAW = ("git ", "rm ", "mv ", "cp ", "sed ")


def prefixes(rules, kind):
    out = []
    for r in rules["permissions"][kind]:
        m = re.fullmatch(r"Bash\((.*):\*\)", r)
        assert m, r
        out.append(m.group(1))
    return out


def allowed(cmd, rules):
    """Claude Code Bash(<prefix>:*) rules: some allow prefix matches and no deny prefix does."""
    if any(cmd.startswith(p) for p in prefixes(rules, "deny")):
        return False
    return any(cmd.startswith(p) for p in prefixes(rules, "allow"))


def code_lines():
    """Fenced lines of the docs: continuations joined, comments dropped, heredoc cut at <<."""
    out = []
    for path in DOCS:
        with open(path) as f:
            text = f.read()
        fenced, pending = False, ""
        for raw in text.splitlines():
            if raw.strip().startswith("```"):
                fenced, pending = not fenced, ""
                continue
            if not fenced:
                continue
            line = pending + raw.strip()
            if line.endswith("\\"):
                pending = line[:-1].rstrip() + " "
                continue
            pending = ""
            if not line or line.startswith("#"):
                continue
            if "<<" in line:
                line = line.split("<<")[0].strip()
            out.append((path, line.replace("${CLAUDE_PLUGIN_ROOT}", ROOT)))
    return out


class AllowlistTest(unittest.TestCase):
    def test_settings_shape(self):
        s = coordinator_setup.settings(ROOT)
        self.assertEqual(s["permissions"]["defaultMode"], "acceptEdits")
        self.assertEqual(s["permissions"]["deny"], [
            "Bash(orca terminal send:*)", "Bash(orca automations:*)", "Bash(orca agent:*)",
            "Bash(gh api:*)", "Bash(git push --force:*)", "Bash(git push -f:*)"])
        hooks = s["hooks"]["SessionStart"]
        self.assertEqual(len(hooks), 1)
        self.assertEqual(hooks[0]["matcher"], "compact")
        self.assertEqual(hooks[0]["hooks"], [{"type": "command",
                         "command": f"python3 -I {ROOT}/scripts/state.py note show"}])
        allow = s["permissions"]["allow"]
        for p in ("orca repo list", "orca orchestration inbox", "gh pr create", "gh pr list",
                  "gh pr view", "pgrep -f", f"python3 -I {ROOT}/scripts/state.py",
                  f"python3 -I {ROOT}/scripts/coord.py", f"python3 -I {ROOT}/scripts/mission_ops.py"):
            self.assertIn(f"Bash({p}:*)", allow)
        self.assertFalse(any(r in allow for r in ("Bash(orca:*)", "Bash(gh:*)", "Bash(git:*)")))

    def test_allowed_matching(self):
        s = coordinator_setup.settings(ROOT)
        self.assertTrue(allowed("orca status --json", s))
        self.assertFalse(allowed("orca terminal send --terminal x", s))
        self.assertFalse(allowed("orca agent launch --agent claude", s))
        self.assertFalse(allowed("gh api /user", s))
        self.assertFalse(allowed("python3 -I /other/scripts/state.py run", s))

    def test_every_skill_command_allowed(self):
        s = coordinator_setup.settings(ROOT)
        lines = [(p, l) for p, l in code_lines() if l.startswith(CHECKED)]
        self.assertTrue(lines)
        bad = [f"{os.path.basename(p)}: {l}" for p, l in lines if not allowed(l, s)]
        self.assertEqual(bad, [])

    def test_every_fenced_line_is_checked(self):
        # a fenced line outside CHECKED would skip test_every_skill_command_allowed
        bad = [f"{os.path.basename(p)}: {l}" for p, l in code_lines() if not l.startswith(CHECKED)]
        self.assertEqual(bad, [])

    def test_terminal_list_and_send_allowed(self):
        s = coordinator_setup.settings(ROOT)
        self.assertTrue(allowed("orca terminal list --limit 1000 --json", s))
        self.assertTrue(allowed("orca orchestration send --to run:R --type question --subject s --body b", s))

    def test_no_raw_git_or_rm_in_skill(self):
        bad = [f"{os.path.basename(p)}: {l}" for p, l in code_lines() if l.startswith(RAW)]
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
