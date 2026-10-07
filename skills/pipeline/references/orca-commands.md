# Orca and gh commands the pipeline uses

Resolve the executable as the `orchestration` skill says (`orca` on this machine). Prefer
`--json`. Record every id the receipt returns in the state file the same turn.

```text
orca status --json
orca orchestration run-create --objective "<id>: <title>" --json            # -> run_id
orca orchestration run-use --id <run_id> --json          # rebind: one coordinator terminal, one bound Run

# readers, senior, planner: current worktree
orca orchestration worker-start --spec "<spec text>" --task-title "<role> <id>" \
  --worktree current --agent claude --model sonnet --effort medium --json   # reader
orca orchestration worker-start --spec "..." --task-title "senior <id>" \
  --worktree current --agent claude --model opus --effort high --json
orca orchestration worker-start --spec "..." --task-title "planner <id>" \
  --worktree current --agent claude --model opus --effort medium --json
# a reader on another registered repo (e.g. the backend): exact workspace, never `current`
orca orchestration worker-start --spec "..." --task-title "reader <angle> <id>" \
  --worktree path:/abs/path/of/registered/repo --agent claude --model sonnet --effort medium --json

# worktree after the plan
orca worktree create --name <id> --base-branch <base> --json                 # -> path
git -C <path> switch -c feature/<id>-<slug>

# implementers, reviewer, greptile reviewer: mission worktree
orca orchestration worker-start --spec "..." --task-title "build <id> task <n>" \
  --worktree name:<id> --agent claude --model opus --effort low --json
orca orchestration worker-start --spec "..." --task-title "build <id> task <n>" \
  --worktree name:<id> --terminal <handle> --json                         # reuse (serial build only; a fix round is a fresh worker)
orca orchestration worker-start --spec "..." --task-title "review <id> r<n>" \
  --worktree name:<id> --agent claude --model opus --effort high --json
orca orchestration worker-start --spec "..." --task-title "greptile <id> PR <n>" \
  --worktree name:<id> --agent claude --model opus --effort high --json

# wait (ALWAYS background Bash, see SKILL.md Waiting), answer, settle
orca orchestration check --run <run_id> --wait --types "worker_done,escalation,question" --timeout-ms 900000 --json
orca orchestration check --run <run_id> --peek --json                      # read-only look between wakes
orca orchestration reply --id <message_id> --body "<answer>" --json
orca orchestration check --run <run_id> --ack <delivery_id> --wait --types "worker_done,escalation,question" --timeout-ms 900000 --json
orca orchestration inbox --limit 20 --json                                 # read-only, across runs
orca orchestration worker-show --dispatch <dispatch_id> --json             # -> terminal handle
orca orchestration worker-release --dispatch <dispatch_id> --json        # right after its worker_done
orca terminal close --terminal <handle> --json                            # when release says `retained` (user typed there)
orca orchestration worker-list --run <run_id> --terminal-state reclaimable --json   # must be empty before you end

# PR (stage `pr`); <base> is the mission's base_branch, <owner_repo> from the state file; cwd never matters
git -C <worktree> push -u origin <branch>
sed -n 1p <sp>/pr-body.md > <sp>/pr-title.txt; sed 1d <sp>/pr-body.md > <sp>/pr-body-rest.md
gh pr create --repo <owner_repo> --base <base> --head <branch> --title "$(cat <sp>/pr-title.txt)" --body-file <sp>/pr-body-rest.md
#   on a GraphQL "Something went wrong": `gh pr list --repo <owner_repo> --head <branch> --state all --json number,url` first; retry only if empty
gh pr view <n> --repo <owner_repo> --json number,url,state,headRefOid,mergedAt,mergeCommit,closedAt

# close (stage `ready` -> done)
gh pr list --repo <owner_repo> --head <branch> --state merged --json number,mergeCommit,mergedAt

# UI helpers
orca terminal rename --terminal <handle> --title "<role> <id>"
orca terminal switch --terminal <handle>        # give this line to the user
```

## Watchers (background Bash, `run_in_background: true`)

This Mac has no `timeout` binary: never wrap `gh` in `timeout`, the call fails silently and
the watcher never fires. Plain `gh ... 2>/dev/null || echo ""` is enough.

```bash
# Greptile delay: the PR is open; wake me 5 minutes later
sleep 300; echo "greptile delay over for <id> PR <n>"

# Merge watcher: poll every 5 min, exit on MERGED or CLOSED, give up after 6 h (re-arm on exit 2)
deadline=$(( $(date +%s) + 6*3600 ))
until [ "$(date +%s)" -ge "$deadline" ]; do
  r=$(gh pr view <n> --repo <owner_repo> --json number,state,mergedAt,mergeCommit,closedAt 2>/dev/null || echo "")
  st=$(printf '%s' "$r" | python3 -I -c 'import json,sys
try: print(json.load(sys.stdin).get("state",""))
except Exception: print("")')
  if [ "$st" = "MERGED" ] || [ "$st" = "CLOSED" ]; then echo "$r" > <scratchpad>/pipeline/<id>/pr-final.json; echo "PR <n> (<id>) is $st: $r"; exit 0; fi
  sleep 300
done
echo "TIMEOUT: PR <n> still open after 6h"; exit 2
```

## Checks before you trust a receipt

- `worker-start` exit 0 only means ready. Non-zero: read `failedStage` and load the
  orchestration skill's `recovery-and-cleanup` reference. Do not relaunch.
- `selector_not_found` on `--worktree path:`: the folder is not a registered Orca repo; `orca
  repo list --json` shows what is (a monorepo registers at its root, not a sub-folder).
- Compare `launch.requested` with `launch.effective`. If `effective` drops the effort, say so
  in the state `note`; do not claim the effort.
- `worker_done` must carry the Dispatch id you expect. A done from another id is not yours
  (a re-sent done from an already settled dispatch: ack it, ignore it).
- A `consumer_fenced` error on `check`: this terminal is bound to another Run; `run-use` the
  Run you need. Only one Run is bound at a time, so only one background wait is live at a time.
- A `consumer_fenced` error on `--ack` after a `run-use` round trip: the Delivery id belongs to
  the old consumer generation. Run a plain consuming `check --run <run_id>` (it replays the same
  batch under a new Delivery id) and ack that id.
- Three empty waits in a row: `worker-list --include-remote --json` and follow each row's
  `projection.nextAction`.
