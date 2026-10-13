# Orca and gh commands the pipeline uses

Resolve the executable as the `orchestration` skill says (`orca` on this machine). Prefer
`--json`. Record every id the receipt returns in the state file the same turn.

```text
orca status --json
# Binding: once per session, every mission shares this Run (<shared>); SKILL.md step 1
python3 -I ${CLAUDE_PLUGIN_ROOT}/scripts/state.py run                       # -> saved id or empty line; exit 3 = bad coordinator.json
orca orchestration run-current --json                   # already bound to the saved id? done
orca orchestration run-show --id <saved_id> --json      # error.code run_not_found -> create below
orca orchestration run-use --id <saved_id> --json       # found: bind; any error: tell the user, stop
orca orchestration run-create --objective "pipeline coordinator" --json     # only: no saved id or run_not_found
python3 -I ${CLAUDE_PLUGIN_ROOT}/scripts/state.py run --set <run_id>        # save it for restarts
# every worker-start below also carries --run <shared>; record result.dispatchId with dispatches+=

# readers, senior, planner: current worktree
orca orchestration worker-start --spec "<spec text>" --task-title "<role> <id>" \
  --worktree current --agent claude --model claude-haiku-5-5 --effort high --run <shared> --json   # reader
orca orchestration worker-start --spec "..." --task-title "senior <id>" \
  --worktree current --agent claude --model opus --effort high --run <shared> --json
orca orchestration worker-start --spec "..." --task-title "planner <id>" \
  --worktree current --agent claude --model opus --effort medium --run <shared> --json
# a reader on another registered repo (e.g. the backend): exact workspace, never `current`
orca orchestration worker-start --spec "..." --task-title "reader <angle> <id>" \
  --worktree path:/abs/path/of/registered/repo --agent claude --model claude-haiku-5-5 --effort high --run <shared> --json

# ticket state (missions with a ticket; never --current: the coordinator is not in the linked worktree)
orca linear issue <TICKET> --json                                            # -> state name + type
orca linear status set <TICKET> --to "In Progress" --json                     # step 5, only from triage/backlog/unstarted
orca linear status set <TICKET> --to "Dev Complete" --json                    # Finish, only from In Progress

# worktree after the plan
orca worktree create --name <id> --base-branch <base> --json                 # -> path
git -C <path> switch -c feature/<id>-<slug>
git -C <repo> ls-files --error-unmatch <spec-or-plan>                       # exit 1 = untracked: rm from <repo>; exit 0 or other: keep
orca worktree rm --worktree name:<id> --json                                 # Finish only; never --force

# implementers, reviewer, greptile reviewer: mission worktree
orca orchestration worker-start --spec "..." --task-title "build <id> task <n>" \
  --worktree name:<id> --agent claude --model opus --effort low --run <shared> --json
orca orchestration worker-start --spec "..." --task-title "build <id> task <n>" \
  --worktree name:<id> --terminal <handle> --run <shared> --json                         # reuse (serial build only; a fix round is a fresh worker)
orca orchestration worker-start --spec "..." --task-title "review <id> r<n>" \
  --worktree name:<id> --agent claude --model opus --effort high --run <shared> --json
orca orchestration worker-start --spec "..." --task-title "greptile <id> PR <n>" \
  --worktree name:<id> --agent claude --model opus --effort high --run <shared> --json

# wait (ALWAYS background Bash, see SKILL.md Waiting), answer, settle
pgrep -f "orchestration check --run <shared> .*--wait"                     # exit 0 = a wait is running: do not arm another
orca orchestration check --run <shared> --wait --types "worker_done,escalation,question" --timeout-ms 900000 --json > <scratchpad>/pipeline/inbox.json
orca orchestration check --run <shared> --peek --json                      # read-only look between wakes
python3 -I ${CLAUDE_PLUGIN_ROOT}/scripts/state.py owner <dispatchId>         # dispatchId = JSON.parse(message.payload).dispatchId (payload is a JSON string; never from_handle)
                                # exit 0 "<slug> <id> live|settled"; 3 no owner; 4 two owners; other = failed
orca orchestration reply --id <message_id> --body "<answer>" --json
orca orchestration check --run <shared> --ack <delivery_id> --wait --types "worker_done,escalation,question" --timeout-ms 900000 --json > <scratchpad>/pipeline/inbox.json
orca orchestration worker-show --dispatch <dispatch_id> --json             # -> terminal handle; per-Dispatch cleanup over the mission's dispatches
orca orchestration worker-release --dispatch <dispatch_id> --json        # right after its worker_done
orca terminal close --terminal <handle> --json                            # when release says `retained` (user typed there)
orca orchestration worker-list --run <shared> --include-remote --json     # three empty waits only; rows carry dispatchId; page with --cursor

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
- A batch holds every mission's messages. Route each one by `state.py owner
  <payload.dispatchId>` (SKILL.md Waiting): `live` → act on that mission; `settled` (a re-sent
  done from an already settled dispatch) → ignore it; exit 3 → tell the user. Never drop a
  message as "not yours" because it belongs to another mission.
- A `consumer_fenced` error on `check` or `worker-start`: another terminal took the shared Run
  (it fences even `--peek`). Tell the user; do not rebind on your own. Rebind with Binding only
  on the user's word.
- A `consumer_fenced` error on `--ack` after a rebind: the Delivery id belongs to the old
  consumer generation. Run a plain consuming `check --run <shared>` (it replays the same batch
  under a new Delivery id) and ack that id.
- Three empty waits in a row: `worker-list --run <shared> --include-remote --json`, follow
  `page.nextCursor` while `page.hasMore`, map each row with `state.py owner <row.dispatchId>`
  and follow `projection.nextAction` only on `live` rows.
