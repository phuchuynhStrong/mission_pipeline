---
description: Run a mission through read > spec > plan only, then commit spec.md + plan.html to docs/preparation/
argument-hint: "<TICKET or mission text> [--base <branch>: shown in the plan header; the commit goes on the current branch]"
---

Load the `pipeline` skill (Skill tool, `pipeline:pipeline`) and run this mission in plan mode,
exactly as if the user typed `/pipeline --plan-only $ARGUMENTS`.
