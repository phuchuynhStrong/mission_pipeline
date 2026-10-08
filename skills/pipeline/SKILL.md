---
name: pipeline
description: Use when the user hands over a mission (a Linear ticket, a feature, a bug) to run through supervised Orca workers, asks where a mission stands, or types /pipeline.
---

# Pipeline

You are the **coordinator**. Workers read, design, plan, build and review. You only move
paths and outcomes between them and keep the state file current. **You never open, read,
grep or summarise a reading, spec, plan, diff, review report or PR body.** A path and a
`worker_done` outcome are your whole input.

**REQUIRED SUB-SKILL:** load `orchestration` first and run every Orca command exactly as
`references/orca-commands.md` spells it. **No Agent-tool subagents in this flow:** the user
must be able to type into the senior's terminal, and only Orca workers have one.

## Roles

| Role | Agent | `--model` | `--effort` | Worktree | Reads | Reports (`worker_done`) |
|---|---|---|---|---|---|---|
| reader (1..N) | claude | claude-haiku-5-5 | high | current (or an exact registered repo) | mission.md | `--report-path` readings file |
| senior | claude | opus | high | current | mission.md + readings | `--report-path` spec path |
| planner | claude | opus | medium | current | spec | `--report-path` plan path, body `tasks: N; parallel: yes/no; spec-is-plan: yes/no` |
| implementer | claude | opus | low | mission worktree | plan (one task) or review report (fix round) | `--outcome`, `--files-modified` |
| reviewer | claude | opus | high | mission worktree | spec + plan + `git diff` | body `APPROVED` (+ writes pr-body.md), `FIX: <line>` or `NEEDS_USER: <line>` |
| greptile reviewer | claude | opus | high | mission worktree | PR comments via `gh` + code | body `GREPTILE_OK: <score>` or `NEEDS_USER: <score> — <line>` |

Task-spec templates: `references/roles.md`. Fill every `{placeholder}`; a worker sees only
its spec.

**Terminals close when the job is done.** The moment a worker's `worker_done` is recorded in
the state file, run `worker-release --dispatch <id>`. If the receipt says `retained` (Orca
never releases a terminal the user typed in, so the senior's always is), run
`orca terminal close --terminal <handle> --json`. Two exceptions keep their terminal open:
a `NEEDS_USER` outcome (reviewer, greptile reviewer) or an implementer gap, because the user
must read it; and an implementer that will be reused for the next task (`parallel: no`),
released after its last task. `events+="released <role> <handle>"` each time.

## Places

| Thing | Where |
|---|---|
| mission id | ticket id lower-case (`wbs-12345`); no ticket: `YYYY-MM-DD-<slug>` |
| base branch | `--base <branch>` in the `/pipeline` arguments; else the repo's default branch. Stored as `base_branch` at `state.py new`; every worktree, diff, PR uses it |
| owner/repo | from `git -C <repo> remote get-url origin` at intake, stored as `owner_repo`; every `gh` call carries `--repo <owner_repo>` so the cwd never matters |
| mission text, readings | `<scratchpad>/pipeline/<id>/mission.md`, `.../readings/<angle>.md` |
| review reports | `.../review.md`, `.../review-2.md`, ... (one per round) |
| PR body, Greptile report | `.../pr-body.md` (written by the reviewer), its split `.../pr-title.txt` + `.../pr-body-rest.md`, `.../greptile-review.md` |
| inbox, watcher outputs | `.../inbox.json`, `.../pr.json`, `.../pr-final.json` |
| spec | `<repo>/docs/superpowers/specs/YYYY-MM-DD-<id>-<slug>-design.md` |
| plan | `<repo>/docs/superpowers/plans/YYYY-MM-DD-<id>-<slug>.md` |
| state (git-free) | `~/.claude/pipeline/<repo-basename>/<id>.json`, written only with `python3 -I ${CLAUDE_PLUGIN_ROOT}/scripts/state.py` (`new`, `set`, `done`, `abort`, `show`, `list`) |
| worktree | `orca worktree create --name <id> --base-branch <base>`; branch `feature/<id>-<slug>` |

## Loop

1. **Intake.** Get the ticket text (orca-linear skill if it is a Linear id). Parse `--base
   <branch>` from the arguments (default: the repo's default branch). Write `mission.md`.
   `state.py new ... --base-branch <base>`, then `state.py set ... owner_repo=<owner/repo>`. `orca status --json`, then `run-create` and store
   `run_id`. Open the board: `/pboard`.
2. **Read.** Pick 1 to 4 reader angles from the mission text (UI, data, patterns, tests). Start
   all readers in one wave, `--worktree current`, arm the wait (Waiting) and end the turn. On
   each `worker_done` record the path and release that reader. Continue when every reader is
   released.
3. **Spec.** Start the senior with mission + readings paths and the spec destination. Rename its
   terminal `senior <id>`. Set `stages.spec.status=waiting_user`, `note="brainstorm with senior"`, `attention.terminal=<h>`, `attention.reason="brainstorm with senior"`, and tell the user `orca terminal switch --terminal <h>`, arm the wait and end the turn. On `worker_done` record the spec path, set `attention=null`, and close the senior's terminal (release, then `terminal close` on `retained`).
4. **Plan.** Start the planner with the spec path and plan destination, arm the wait. On `worker_done` parse
   the body line into `stages.plan.tasks`, `stages.plan.parallel`; if `spec-is-plan: yes`, the plan
   path is the spec path. Release the planner.
5. **Worktree.** `orca worktree create --name <id> --base-branch <base> --json` → path. In it:
   `git switch -c feature/<id>-<slug>`; `cp` spec and plan to the same relative paths;
   `git add` + `git commit -m "#<TICKET> docs(<scope>): add spec and plan"`. Record path and
   branch. Confirm `worker-list --run <run_id> --terminal-state reclaimable` is empty; release
   anything it still lists.
6. **Build.** `parallel: no` → one implementer, task 1; on `succeeded` reuse its terminal
   (`--terminal <handle>`) for task 2, and so on. `parallel: yes` → one implementer per task in one
   wave, all `--worktree name:<id>`. Arm the wait after every start. Update `stages.build.done` after each. Release an
   implementer when its last task `succeeded` (parallel: each on its own `worker_done`; serial:
   after task N). A `failed` outcome stops the build and keeps that terminal open: set `note`
   and `attention.terminal=<handle>`, tell the user the handle, wait for their word.
7. **Review.** When `done == tasks`, start the reviewer in the worktree (round 1; report
   `review.md`), `stages.review.rounds=1`, arm the wait. Act on the first word of its body:
   - `APPROVED` → release the reviewer, `stages.review.status=done`, go to step 8. The reviewer
     has written `pr-body.md`; you pass its path on, you do not read it.
   - `FIX:` → release the reviewer; start a fresh fix-round implementer (roles.md "implementer (fix
     round)", `--worktree name:<id> --agent claude --model opus --effort low`; the build
     implementer's terminal is already released), arm the wait. On
     `succeeded` release it and start the reviewer again (round N+1, report `review-N+1.md`,
     previous reports listed). At most **2 fix rounds**: a third `FIX:` is handled as
     `NEEDS_USER` with `note="review: 2 fix rounds did not converge"`.
   - `NEEDS_USER:` → `stages.review.status=waiting_user attention.terminal=<handle>
     attention.reason="<reason>"`, keep the reviewer's terminal, tell the user its handle and the
     one-line reason, end the turn. The user decides; you do not dispatch a fix unasked. When
     the user gives their decisions (in chat, or relayed by the reviewer as a `status` message),
     release and close the reviewer, start a fix-round implementer with the decisions, then
     re-review as above (this round does not count toward the 2-round cap).
8. **PR.** `stage=pr stages.pr.status=active note="opening PR"`. From the worktree:
   `git -C <worktree> push -u origin <branch>`; split the body without reading it:
   `sed -n 1p pr-body.md > pr-title.txt`, `sed 1d pr-body.md > pr-body-rest.md`; if the title
   file is empty or longer than 70 characters, the title is `#<TICKET> feat(<scope>): <mission
   title>` instead. Then `gh pr create --repo <owner_repo> --base <base> --head <branch>
   --title "$(cat pr-title.txt)" --body-file pr-body-rest.md`. On a GitHub "Something went
   wrong" error, `gh pr list --repo <owner_repo> --head <branch> --state all` first and retry
   only if it is empty. Record `stages.pr.number`, `stages.pr.url`,
   `note="PR #<n> open; Greptile check in 5 min"`. Then, in one response, arm two background
   commands: the Greptile delay (`sleep 300`) and the merge watcher (orca-commands.md
   Watchers). No Orca wait is needed on this Run until the greptile reviewer starts. The pipeline opens the PR itself: the user's request to run
   the mission is the authorisation to push this branch and open this one PR; nothing else is
   ever pushed.
   - When the delay wakes you: start the greptile reviewer (roles.md), arm the wait.
     `GREPTILE_OK` → release it, `stages.pr.greptile=<score>`, `stage=ready
     stages.pr.status=done note="ready: PR #<n> open, Greptile <score>; closes on merge"`.
     `NEEDS_USER:` → `stages.pr.status=waiting_user attention.terminal=<handle>
     attention.reason="Greptile <score>: <line>"`, keep its terminal, tell the user the handle,
     the score and the one line. The user decides whether to fix. On their word: release and close the greptile
     reviewer's terminal, dispatch a fix-round implementer with the Greptile report, on
     `succeeded` release it and `git -C <worktree> push` (same PR), then `attention=null
     stage=ready stages.pr.status=done`. If the user declines: release and close the greptile
     terminal, `attention=null stage=ready stages.pr.status=done`.
   - When the merge watcher wakes you with `MERGED`: `state.py done <repo-basename> <id>
     --reason "MERGED into <base>: PR #<n> (<sha>, <mergedAt>)"`, release any worker the
     mission still holds, tell the user. `CLOSED` without merge: `note="PR #<n> closed
     unmerged"`, `attention=null`, tell the user and wait for their word. Exit 2 (6 h without a
     result): re-arm the watcher.
9. **Close.** A `ready` mission stays on the board until its PR is merged. The merge watcher
   normally closes it; whenever the user says a mission is done or asks where missions stand,
   also run for every `pr`/`ready` mission:
   `gh pr list --repo <owner_repo> --head <branch> --state merged --json number,mergeCommit,mergedAt`. A merged PR, or the user's word, → `state.py done <repo-basename> <id>
   --reason "MERGED into <base>: PR #<n> (<sha>, <mergedAt>)"` (or `--reason "user: <their words>"`).
   `done` hides the row. The worktree and branch stay; you delete nothing unless asked.
10. **Abort** (only when the user says stop). Release every worker of the mission
   (`worker-release`, or `worker-stop` then `worker-abandon` when stop fails), stop its
   watchers (`TaskStop`), then `state.py abort <repo-basename> <id> --reason "<one line>"`.
   Tell the user what was left behind: untracked spec/plan files, a worktree, a branch, an open
   PR. You delete nothing.

State vocabulary: `stage` is one of `read spec plan worktree build review pr ready done aborted`
(`pr` = PR open, Greptile check running or waiting on the user; `ready` = Greptile done,
waiting for the merge; `done` and `aborted` are terminal: the board hides them and stops
auto-opening); every
`stages.<name>.status` is one of `pending active waiting_user done failed`. Create with
`state.py new <repo-basename> <id> --ticket <TICKET> --title "<title>" --repo <repo> --base-branch <base>`.
Every stage change is one `state.py set <repo-basename> <id> stage=<name> stages.<name>.status=<status> note="<board line>" events+="<what happened>"`,
plus the ids and paths the receipt gave (`run_id=`, `stages.spec.path=`, `stages.build.workers+=`,
`stages.pr.number=`). The board polls the file; nothing else updates it.

**Attention = a terminal the user should open.** Whenever you tell the user a terminal handle
(senior brainstorm, implementer `failed`, reviewer or greptile `NEEDS_USER`, an `escalation`),
set it in the same `state.py set`: `attention.terminal=<handle> attention.reason="<one line>"`.
The board turns that into a switch button (hotkeys 1..9 down the switch rows) that runs `orca terminal
switch`. Clear it with `attention=null` in the `set` that records the stage moving on or the
user's answer.

## Waiting

Never block the turn on a worker. Every wait is one **background** Bash call
(`run_in_background: true`) that exits when a batch lands or the timeout ends; the harness
wakes you when it exits:

```text
orca orchestration check --run <run_id> --wait --types "worker_done,escalation,question" --timeout-ms 900000 --json \
  > <scratchpad>/pipeline/<id>/inbox.json
```

Then end the turn. On the wake, read `inbox.json`, act on every message in the batch, and
re-arm the same way with `check --ack <delivery_id> --wait ...` (the ack and the next wait are
one call). Rules:

- One open `check --wait` per run at a time. A second consumer races on the same FIFO. Any
  read you need between wakes is `--peek`.
- **One bound Run per coordinator terminal.** `run-create` and `run-use` rebind this terminal;
  a background wait on the previously bound Run dies with `consumer_fenced`. With two missions
  live, keep the wait on the Run that has a worker running; the other Run reaches you through
  Orca's nudge ("You have N orchestration messages") and `orchestration inbox` (read-only,
  across Runs). On a nudge for the other Run: `run-use` it, consume, act, re-arm there.
- A wake with an empty result or a timeout is a checkpoint, not a failure: re-arm. Three empty
  wakes in a row: `worker-list --include-remote --json` and follow each row's
  `projection.nextAction`.
- A wake is not the user's reply. It can land while they type in a worker's terminal; their
  word still arrives as a user message, or as a `status` message the worker relays.
- Watchers (Greptile delay, merge watcher) are background Bash too and run beside the wait;
  they do not touch the Orca FIFO. No `timeout` binary exists on this Mac: a `timeout gh ...`
  fails silently and the watcher never fires.
- A foreground `check --wait` is wrong twice: the harness kills a foreground command at 10 min
  (the wait asks for 15), and you cannot answer the user or update the board while it runs.

## Worker questions

A `question` from a reader, planner or implementer: reply `Decide yourself and record the
assumption in your report.` An `escalation`: set `note` and `attention.terminal=<handle>`, tell
the user the handle, wait; clear `attention` when they have answered. The
senior never asks you; the user is in its terminal. A `question` from the senior that relays a
user request (e.g. "spawn readers on the backend repo") is the user's word: do it, reply with
the paths.

## Red flags, stop

- "I'll skim the spec so the implementer prompt is better." → The planner's body line is all you need.
- "Readings are small, I'll paste them into the senior prompt." → Paths only.
- "The reviewer found something small, I'll dispatch a fix." → Only a `FIX:` verdict dispatches a fix round. `NEEDS_USER` waits for the user.
- "I'll write the PR body myself from the commit list." → The reviewer wrote `pr-body.md`; split it, do not read it.
- "Greptile flagged a real bug, I'll fix and push." → Notify; the user decides.
- "Agent tool is quicker for the readers." → No terminal for the user; Orca only.
- "Worktree first, it saves a step." → After the plan, never before.
- "I'll run `check --wait` in the foreground so I don't miss it." → Background only (Waiting).
- "`timeout 30 gh ...` is safer." → No such binary here; the watcher dies silently.

## Board

`/pboard` opens the pane this skill ships (`hooks/`). One line per mission: a status glyph (`?`
asks, `!` failed, `✓` merge-ready, `»` working, `·` idle), the ticket, the stage word (`read`,
`spec`, `plan`, `tree`, `build`, `review`, `pr`), then `attention.reason`, else `note`, cut to the
line. Rows that need the user come first: `!` when a stage `failed`, `?` or `✓` while it waits on
the user (`waiting_user`, `attention`, `ready`), then running rows with the time since `updated` at
the right edge. A legend line sits under the rows. A row with `attention` carries a switch button
(`1: ⏎`, its hotkey digit then Enter). A `ready` mission stays
listed until `state.py done` (PR merged or the user's word). Done and aborted missions are
hidden; `state.py list --all` still shows them. Orca's own app shows
the Run, Tasks and Dispatches; the board shows the mission stages.
