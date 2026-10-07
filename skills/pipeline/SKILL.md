---
name: pipeline
description: Use when the user hands over a mission (a Linear ticket, a feature, a bug) to run through supervised Orca workers, asks where a mission stands, or types /pipeline.
---

# Pipeline

You are the **coordinator**. Workers read, design, plan, build and review. You only move
paths and outcomes between them and keep the state file current. **You never open, read,
grep or summarise a reading, spec, plan or diff.** A path and a `worker_done` outcome are
your whole input.

**REQUIRED SUB-SKILL:** load `orchestration` first and run every Orca command exactly as
`references/orca-commands.md` spells it. **No Agent-tool subagents in this flow:** the user
must be able to type into the senior's terminal, and only Orca workers have one.

## Roles

| Role | Agent | `--model` | `--effort` | Worktree | Reads | Reports (`worker_done`) |
|---|---|---|---|---|---|---|
| reader (1..N) | claude | sonnet | medium | current | mission.md | `--report-path` readings file |
| senior | claude | opus | high | current | mission.md + readings | `--report-path` spec path |
| planner | claude | opus | medium | current | spec | `--report-path` plan path, body `tasks: N; parallel: yes/no; spec-is-plan: yes/no` |
| implementer | claude | opus | low | mission worktree | plan (one task) | `--outcome`, `--files-modified` |
| reviewer | claude | opus | high | mission worktree | spec + plan + `git diff` | `succeeded` body `APPROVED` or `failed` body `NEEDS_USER: <one line>` |

Task-spec templates: `references/roles.md`. Fill every `{placeholder}`; a worker sees only
its spec.

**Terminals close when the job is done.** The moment a worker's `worker_done` is recorded in
the state file, run `worker-release --dispatch <id>`. If the receipt says `retained` (Orca
never releases a terminal the user typed in, so the senior's always is), run
`orca terminal close --terminal <handle> --json`. Two exceptions keep their terminal open:
a `failed` outcome (implementer gap, reviewer `NEEDS_USER`) because the user must read it, and
an implementer that will be reused for the next task (`parallel: no`), released after its
last task. `events+="released <role> <handle>"` each time.

## Places

| Thing | Where |
|---|---|
| mission id | ticket id lower-case (`wbs-12345`); no ticket: `YYYY-MM-DD-<slug>` |
| mission text, readings, review | `<scratchpad>/pipeline/<id>/mission.md`, `.../readings/<angle>.md`, `.../review.md` |
| spec | `<repo>/docs/superpowers/specs/YYYY-MM-DD-<id>-<slug>-design.md` |
| plan | `<repo>/docs/superpowers/plans/YYYY-MM-DD-<id>-<slug>.md` |
| state (git-free) | `~/.claude/pipeline/<repo-basename>/<id>.json`, written only with `python3 -I ${CLAUDE_PLUGIN_ROOT}/scripts/state.py` (`new`, `set`, `done`, `abort`, `show`, `list`) |
| worktree | `orca worktree create --name <id>`; branch `feature/<id>-<slug>` |

## Loop

1. **Intake.** Get the ticket text (orca-linear skill if it is a Linear id). Write
   `mission.md`. `state.py new`. `orca status --json`, then `run-create` and store `run_id`.
   Open the board: `/pipeline-board`.
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
7. **Review.** When `done == tasks`, start the reviewer in the worktree and arm the wait. `succeeded` → release
   the reviewer, `stage=ready stages.review.status=done note="ready: <branch>; open a PR, mission
   closes on merge"`, confirm `worker-list ... --terminal-state reclaimable` is empty, tell the
   user: mission id, branch, worktree path, "ready for you to look at". `failed` →
   `stages.review.status=waiting_user attention.terminal=<handle> attention.reason="<reason>"`,
   keep the reviewer's terminal, tell the user its handle and the one-line reason. The user decides the fix; you do not dispatch one unasked.
8. **Close.** A `ready` mission stays on the board until its PR is merged or the user says the
   mission is done. Whenever the user says a mission is done, merged, or asks where missions
   stand, first run for every `ready` mission:
   `gh pr list --repo <owner/repo> --head <branch> --state merged --json number,mergeCommit,mergedAt`
   (from `<repo>`). A merged PR, or the user's word, → `state.py done <repo-basename> <id>
   --reason "MERGED into <base>: PR #<n> (<sha>, <mergedAt>)"` (or `--reason "user: <their words>"`).
   `done` hides the row. The worktree and branch stay; you delete nothing unless asked.
9. **Abort** (only when the user says stop). Release every worker of the mission
   (`worker-release`, or `worker-stop` then `worker-abandon` when stop fails), then
   `state.py abort <repo-basename> <id> --reason "<one line>"`. Tell the user what was left
   behind: untracked spec/plan files, a worktree, a branch. You delete nothing.

State vocabulary: `stage` is one of `read spec plan worktree build review ready done aborted`
(`ready` = reviewed, waiting for the PR to merge; `done` and `aborted` are terminal: the board
hides them and stops auto-opening); every
`stages.<name>.status` is one of `pending active waiting_user done failed`. Create with
`state.py new <repo-basename> <id> --ticket <TICKET> --title "<title>" --repo <repo> --base-branch <base>`.
Every stage change is one `state.py set <repo-basename> <id> stage=<name> stages.<name>.status=<status> note="<board line>" events+="<what happened>"`,
plus the ids and paths the receipt gave (`run_id=`, `stages.spec.path=`, `stages.build.workers+=`).
The board polls the file; nothing else updates it.

**Attention = a terminal the user should open.** Whenever you tell the user a terminal handle
(senior brainstorm, implementer `failed`, reviewer `NEEDS_USER`, an `escalation`), set it in the
same `state.py set`: `attention.terminal=<handle> attention.reason="<one line>"`. The board
turns that into a `switch` button (hotkey = row number) that runs `orca terminal switch`. Clear
it with `attention=null` in the `set` that records the stage moving on or the user's answer.

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
- Each mission waits on its own `--run <run_id>`, so two missions never share a wake.
- A wake with an empty result or a timeout is a checkpoint, not a failure: re-arm. Three empty
  wakes in a row: `worker-list --include-remote --json` and follow each row's
  `projection.nextAction`.
- A wake is not the user's reply. It can land while they type in a worker's terminal; their
  word still arrives as a user message.
- A foreground `check --wait` is wrong twice: the harness kills a foreground command at 10 min
  (the wait asks for 15), and you cannot answer the user or update the board while it runs.

## Worker questions

A `question` from a reader, planner or implementer: reply `Decide yourself and record the
assumption in your report.` An `escalation`: set `note` and `attention.terminal=<handle>`, tell
the user the handle, wait; clear `attention` when they have answered. The
senior never asks you; the user is in its terminal.

## Red flags, stop

- "I'll skim the spec so the implementer prompt is better." → The planner's body line is all you need.
- "Readings are small, I'll paste them into the senior prompt." → Paths only.
- "The reviewer found something small, I'll dispatch a fix." → User decides.
- "Agent tool is quicker for the readers." → No terminal for the user; Orca only.
- "Worktree first, it saves a step." → After the plan, never before.
- "I'll run `check --wait` in the foreground so I don't miss it." → Background only (Waiting).

## Board

`/pipeline-board` opens the pane this skill ships (`hooks/`). One row per mission:
`read › spec › plan › tree › build › review`, filled by the state file. The ticket is green while
the pipeline runs, yellow while it waits on the user (`waiting_user`, `attention`, `ready`), red
when a stage `failed`. A row with `attention` carries a `switch` button. A `ready` mission stays
listed until `state.py done` (PR merged or the user's word). Done and aborted missions are
hidden; `state.py list --all` still shows them. Orca's own app shows
the Run, Tasks and Dispatches; the board shows the mission stages.
