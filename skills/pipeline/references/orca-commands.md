# Orca commands the pipeline uses

Resolve the executable as the `orchestration` skill says (`orca` on this machine). Prefer
`--json`. Record every id the receipt returns in the state file the same turn.

```text
orca status --json
orca orchestration run-create --objective "<id>: <title>" --json            # -> run_id

# readers, senior, planner: current worktree
orca orchestration worker-start --spec "<spec text>" --task-title "<role> <id>" \
  --worktree current --agent claude --model sonnet --effort medium --json   # reader
orca orchestration worker-start --spec "..." --task-title "senior <id>" \
  --worktree current --agent claude --model opus --effort high --json
orca orchestration worker-start --spec "..." --task-title "planner <id>" \
  --worktree current --agent claude --model opus --effort medium --json

# worktree after the plan
orca worktree create --name <id> --base-branch <base> --json                 # -> path
git -C <path> switch -c feature/<id>-<slug>

# implementers, reviewer: mission worktree
orca orchestration worker-start --spec "..." --task-title "build <id> task <n>" \
  --worktree name:<id> --agent claude --model opus --effort low --json
orca orchestration worker-start --task <task_id> --terminal <handle> --worktree name:<id> --json   # reuse
orca orchestration worker-start --spec "..." --task-title "review <id>" \
  --worktree name:<id> --agent claude --model opus --effort high --json

# wait, answer, settle — every `check --wait` is a background Bash call (SKILL.md, Waiting)
orca orchestration check --run <run_id> --wait --types "worker_done,escalation,question" --timeout-ms 900000 --json > <scratchpad>/pipeline/<id>/inbox.json
orca orchestration reply --id <message_id> --body "<answer>" --json
orca orchestration check --run <run_id> --ack <delivery_id> --wait --types "worker_done,escalation,question" --timeout-ms 900000 --json > <scratchpad>/pipeline/<id>/inbox.json   # background too
orca orchestration check --run <run_id> --peek --types "worker_done,escalation,question" --json   # read between wakes; never a second --wait on the same run
orca orchestration worker-show --dispatch <dispatch_id> --json             # -> terminal handle
orca orchestration worker-release --dispatch <dispatch_id> --json        # right after its worker_done
orca terminal close --terminal <handle> --json                            # when release says `retained` (user typed there)
orca orchestration worker-list --run <run_id> --terminal-state reclaimable --json   # must be empty before you end

# close (step 8): is the mission's PR merged?
gh pr list --repo <owner/repo> --head <branch> --state merged --json number,mergeCommit,mergedAt

# UI helpers
orca terminal rename --terminal <handle> --title "<role> <id>"
orca terminal switch --terminal <handle>        # give this line to the user
```

Checks before you trust a receipt:

- `worker-start` exit 0 only means ready. Non-zero: read `failedStage` and load the
  orchestration skill's `recovery-and-cleanup` reference. Do not relaunch.
- Compare `launch.requested` with `launch.effective`. If `effective` drops the effort, say so
  in the state `note`; do not claim the effort.
- `worker_done` must carry the Dispatch id you expect. A done from another id is not yours.
- A background wait that exits with no batch is a timeout wake: re-arm it, do not report it.
- Three empty wakes in a row: `worker-list --include-remote --json` and follow each row's
  `projection.nextAction`.
