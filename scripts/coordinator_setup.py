#!/usr/bin/env python3
"""Workspace settings for the persistent coordinator (spec §11).

  coordinator_setup.py settings --plugin-root <abs>   # prints .claude/settings.json

acceptEdits mode, one Bash rule per command the skill uses, deny rules for the rest that
matter. Anything off the list prompts, and a prompt nobody sees stalls the coordinator.
"""
import argparse, json

ORCA = [
    "orca status",
    "orca orchestration check", "orca orchestration reply", "orca orchestration inbox",
    "orca orchestration run-current", "orca orchestration run-show", "orca orchestration run-use",
    "orca orchestration run-create", "orca orchestration worker-start",
    "orca orchestration worker-show", "orca orchestration worker-release",
    "orca orchestration worker-stop", "orca orchestration worker-abandon",
    "orca orchestration worker-list",
    "orca linear issue", "orca linear status set",
    "orca worktree create", "orca worktree rm",
    "orca orchestration send",
    "orca terminal close", "orca terminal rename", "orca terminal list",
    "orca repo list",
]
GH = ["gh pr create", "gh pr list", "gh pr view"]
SCRIPTS = ["state.py", "coord.py", "mission_ops.py"]
DENY = ["orca terminal send", "orca automations", "orca agent", "gh api",
        "git push --force", "git push -f"]


def rule(prefix):
    return f"Bash({prefix}:*)"


def settings(plugin_root):
    root = plugin_root.rstrip("/")
    py = [f"python3 -I {root}/scripts/{s}" for s in SCRIPTS]
    return {
        "permissions": {
            "defaultMode": "acceptEdits",
            "allow": [rule(p) for p in ORCA + GH + py + ["pgrep -f"]],
            "deny": [rule(p) for p in DENY],
        },
        "hooks": {
            "SessionStart": [{
                "matcher": "compact",
                "hooks": [{"type": "command", "command": f"python3 -I {root}/scripts/state.py note show"}],
            }],
        },
    }


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("settings"); s.add_argument("--plugin-root", required=True)
    a = p.parse_args()
    print(json.dumps(settings(a.plugin_root), indent=2))


if __name__ == "__main__":
    main()
