# Orca and gh commands the pipeline uses

Resolve the executable as the `orchestration` skill says (`orca` on this machine). Prefer
`--json`. Record every id the receipt returns in the state file the same turn.

```text
orca status --json
# Binding: every session start, every mission shares this Run (<shared>); SKILL.md step 1
python3 -I ${CLAUDE_PLUGIN_ROOT}/scripts/state.py run --terminal $ORCA_TERMINAL_HANDLE   # first thing: save this terminal
python3 -I ${CLAUDE_PLUGIN_ROOT}/scripts/state.py run                       # -> saved id or empty line; exit 3 = bad coordinator.json
orca orchestration run-current --json                   # already bound to the saved id? done
orca orchestration run-show --id <saved_id> --json      # error.code run_not_found -> create below
orca orchestration run-use --id <saved_id> --json       # found: bind; any error: tell the user, stop
orca orchestration run-create --objective "pipeline coordinator" --json     # only: no saved id or run_not_found
python3 -I ${CLAUDE_PLUGIN_ROOT}/scripts/state.py run --set <run_id>        # save it for restarts
python3 -I ${CLAUDE_PLUGIN_ROOT}/scripts/coord.py seed --run <shared>       # first Binding of the dedicated coordinator only (cutover)
python3 -I ${CLAUDE_PLUGIN_ROOT}/scripts/state.py note show                 # pending decisions, recent answers
python3 -I ${CLAUDE_PLUGIN_ROOT}/scripts/state.py handled open              # started, not answered -> Recovery
# every worker-start below also carries --run <shared>; record result.dispatchId with dispatches+=

# intake: the mission's repo must be registered; owner/repo from its origin
orca repo list --json
python3 -I ${CLAUDE_PLUGIN_ROOT}/scripts/mission_ops.py owner-repo <repo>   # -> owner/repo; exit 3 = no GitHub origin
python3 -I ${CLAUDE_PLUGIN_ROOT}/scripts/state.py file write <slug> <id> mission.md   # text on stdin; never the Write tool

# readers, senior, planner: the mission's repo, never `current` (the coordinator's own folder)
orca orchestration worker-start --spec "<spec text>" --task-title "<role> <id>" \
  --worktree path:<repo> --agent claude --model claude-haiku-5-5 --effort high --run <shared> --json   # reader
orca orchestration worker-start --spec "..." --task-title "senior <id>" \
  --worktree path:<repo> --agent claude --model opus --effort high --run <shared> --json
orca orchestration worker-start --spec "..." --task-title "planner <id>" \
  --worktree path:<repo> --agent claude --model opus --effort medium --run <shared> --json
# a reader on another registered repo (e.g. the backend): exact workspace, never `current`
orca orchestration worker-start --spec "..." --task-title "reader <angle> <id>" \
  --worktree path:/abs/path/of/registered/repo --agent claude --model claude-haiku-5-5 --effort high --run <shared> --json

# ticket state (missions with a ticket; never --current: the coordinator is not in the linked worktree)
orca linear issue <TICKET> --json                                            # -> state name + type
orca linear status set <TICKET> --to "In Progress" --json                     # step 5, only from triage/backlog/unstarted
orca linear status set <TICKET> --to "Dev Complete" --json                    # Finish, only from In Progress

# worktree after the plan
orca worktree create --repo <selector> --name <id> --base-branch <base> --no-parent --json   # -> path
python3 -I ${CLAUDE_PLUGIN_ROOT}/scripts/mission_ops.py docs-commit <slug> <id> --scope <scope>   # branch, copy, commit, then rm untracked from <repo>; -> {"kept","removed"}

# plan mode (SKILL.md Plan mode)
python3 -I ${CLAUDE_PLUGIN_ROOT}/scripts/mission_ops.py prep-commit <slug> <id> --scope <scope>   # P1 -> <sha>; exit 3 = refused
python3 -I ${CLAUDE_PLUGIN_ROOT}/scripts/mission_ops.py prep-status <slug> <id>                   # P1 retry: exit 0 -> <sha>; exit 1 = not committed
python3 -I ${CLAUDE_PLUGIN_ROOT}/scripts/mission_ops.py move-doc <slug> <id> --to <prep_dir>/spec.md   # Switch -> {"path","action": moved|copied}
python3 -I ${CLAUDE_PLUGIN_ROOT}/scripts/mission_ops.py remove-old-plan <slug> <id>               # Cleanup -> {"removed","kept"}
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
pgrep -f "coord.py wait --run <shared>"                                    # exit 0 = a wait is running: do not arm another
python3 -I ${CLAUDE_PLUGIN_ROOT}/scripts/coord.py wait --run <shared> --out <scratchpad>/pipeline/inbox.json   # heartbeat, then check --wait ... --full --json; non-zero: nothing written
python3 -I ${CLAUDE_PLUGIN_ROOT}/scripts/coord.py scan --run <shared>      # after every wake: inbox --limit 100 --full --json -> unanswered rows above the floor; exit 5 = window short
python3 -I ${CLAUDE_PLUGIN_ROOT}/scripts/coord.py advance --run <shared>   # after routing them: move the floor up
python3 -I ${CLAUDE_PLUGIN_ROOT}/scripts/state.py handled get <message_id>   # answered | started | (empty)
python3 -I ${CLAUDE_PLUGIN_ROOT}/scripts/state.py handled start <message_id> --seq <sequence> --type <type> --from <from_handle> --kind outside --summary "<line>"   # before any action; --kind mission for a Dispatch message
python3 -I ${CLAUDE_PLUGIN_ROOT}/scripts/state.py handled answer <message_id> --summary "<line>"   # after the action and the reply
python3 -I ${CLAUDE_PLUGIN_ROOT}/scripts/state.py notice add --kind <kind> --mission <id> --line "<line>"   # every "tell the user"
python3 -I ${CLAUDE_PLUGIN_ROOT}/scripts/state.py notice list              # open notices, for every status reply
python3 -I ${CLAUDE_PLUGIN_ROOT}/scripts/state.py note add "<line>"         # a decision or pending item from an outside ask
orca orchestration check --run <shared> --peek --json                      # read-only look between wakes
python3 -I ${CLAUDE_PLUGIN_ROOT}/scripts/state.py owner <dispatchId>         # dispatchId = JSON.parse(message.payload).dispatchId (payload is a JSON string; never from_handle)
                                # exit 0 "<slug> <id> live|settled"; 3 no owner; 4 two owners; other = failed
orca orchestration reply --id <message_id> --body "<answer>" --json
orca orchestration worker-show --dispatch <dispatch_id> --json             # -> terminal handle; per-Dispatch cleanup over the mission's dispatches
orca orchestration worker-release --dispatch <dispatch_id> --json        # right after its worker_done
orca terminal close --terminal <handle> --json                            # when release says `retained` (user typed there)
orca orchestration worker-list --run <shared> --include-remote --json     # three empty waits only; rows carry dispatchId; page with --cursor

# PR (stage `pr`); <base> is the mission's base_branch, <owner_repo> from the state file; cwd never matters
python3 -I ${CLAUDE_PLUGIN_ROOT}/scripts/mission_ops.py push <slug> <id>                     # git push -u origin <branch>, mission branch only
python3 -I ${CLAUDE_PLUGIN_ROOT}/scripts/mission_ops.py pr-split <slug> <id> --scope <scope>   # -> title; writes <files>/pr-title.txt + pr-body-rest.md
gh pr create --repo <owner_repo> --base <base> --head <branch> --title "<printed title>" --body-file <files>/pr-body-rest.md
#   on a GraphQL "Something went wrong": `gh pr list --repo <owner_repo> --head <branch> --state all --json number,url` first; retry only if empty
gh pr view <n> --repo <owner_repo> --json number,url,state,headRefOid,mergedAt,mergeCommit,closedAt

# close (stage `ready` -> done)
gh pr list --repo <owner_repo> --head <branch> --state merged --json number,mergeCommit,mergedAt

# UI helpers
orca terminal rename --terminal <handle> --title "<role> <id>"
# give the user: orca terminal switch --terminal <handle>
```

## Watchers (background Bash, `run_in_background: true`)

This Mac has no `timeout` binary: never wrap `gh` in `timeout`, the call fails silently and
the watcher never fires. Both watchers are plugin scripts; arm them after the PR opens and
again at every Binding (SKILL.md Binding).

```text
# Greptile delay: the PR is open; wake me 5 minutes later (at Binding: --seconds = time left)
python3 -I ${CLAUDE_PLUGIN_ROOT}/scripts/mission_ops.py greptile-delay <slug> <id> --seconds 300

# Merge watcher: poll every 5 min, exit 0 on MERGED or CLOSED (writes <files>/pr-final.json), exit 2 after 6 h (re-arm)
python3 -I ${CLAUDE_PLUGIN_ROOT}/scripts/mission_ops.py merge-watch <slug> <id>
```

## Checks before you trust a receipt

- `worker-start` exit 0 only means ready. Non-zero: read `failedStage` and load the
  orchestration skill's `recovery-and-cleanup` reference. Do not relaunch.
- `selector_not_found` on `--worktree path:`: the folder is not a registered Orca repo; `orca
  repo list --json` shows what is (a monorepo registers at its root, not a sub-folder).
- Compare `launch.requested` with `launch.effective`. If `effective` drops the effort, say so
  in the state `note`; do not claim the effort.
- A batch holds every mission's messages and outside asks. Route each one as SKILL.md Waiting
  says: no `dispatchId` and type `question` → outside ask, answer it; `state.py owner
  <payload.dispatchId>` `live` → act on that mission; `settled` (a re-sent done from an
  already settled dispatch) → ignore it; exit 3, 4 or other → notice. Never drop a message as
  "not yours" because it belongs to another mission.
- A `consumer_fenced` error on `check` or `worker-start`: another terminal took the shared Run
  (it fences even `--peek`). Tell the user; do not rebind on your own. Rebind with Binding only
  on the user's word.
- Three empty waits in a row: `worker-list --run <shared> --include-remote --json`, follow
  `page.nextCursor` while `page.hasMore`, map each row with `state.py owner <row.dispatchId>`
  and follow `projection.nextAction` only on `live` rows.
