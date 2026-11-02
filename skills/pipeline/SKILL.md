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
| reader (1..N) | claude | claude-haiku-5-5 | high | `path:<repo>` (or another exact registered repo) | mission.md | `--report-path` readings file |
| senior | claude | opus | high | `path:<repo>` | mission.md + readings | `--report-path` spec path |
| planner (also plan only) | claude | opus | medium | `path:<repo>` | spec | `--report-path` plan path, body `tasks: N; parallel: yes/no; spec-is-plan: yes/no` |
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

**Every Dispatch is recorded on its mission.** Every `worker-start` carries `--run <shared>`
(Waiting); in the `state.py set` that records the receipt, add `dispatches+=<dispatchId>`
(also for a reused terminal: it is a new Dispatch). In the `set` that accepts a
`worker_done`, add `settled+=<dispatchId>`. This is how one wait serves every mission.

## Places

| Thing | Where |
|---|---|
| mission id | ticket id lower-case (`wbs-12345`); no ticket: `YYYY-MM-DD-<slug>` |
| base branch | `--base <branch>` in the `/pipeline` arguments; else the repo's default branch. Stored as `base_branch` at `state.py new`; every worktree, diff, PR uses it |
| target repo | required for every mission (path or Orca repo selector). At intake, find it in `orca repo list --json` and take its absolute path; below `<repo>` is always that path. Stored as `repo` at `state.py new`; `<repo-basename>` is its basename. Only `orca worktree create --repo <selector>` takes a selector. The coordinator's own folder is never the target |
| owner/repo | from `mission_ops.py owner-repo <repo>` at intake, stored as `owner_repo`; every `gh` call carries `--repo <owner_repo>` so the cwd never matters |
| mission files | `~/.claude/pipeline/files/<repo-basename>/<id>/` (`state.py file dir <repo-basename> <id>` prints it; below `<files>`). Every file you write there goes through `state.py file write <repo-basename> <id> <name>` (text on stdin), never the Write or Edit tool |
| mission text, readings | `<files>/mission.md`, `<files>/readings/<angle>.md` |
| review reports | `<files>/review.md`, `<files>/review-2.md`, ... (one per round) |
| PR body, Greptile report | `<files>/pr-body.md` (written by the reviewer), its split `<files>/pr-title.txt` + `<files>/pr-body-rest.md` (`mission_ops.py pr-split`), `<files>/greptile-review.md` |
| inbox | `<scratchpad>/pipeline/inbox.json`: one per session, shared by every mission, written by `coord.py wait --out` |
| watcher outputs | `<files>/pr.json`, `<files>/pr-final.json` |
| saved Run | `~/.claude/pipeline/coordinator.json`, one per machine, read and written only with `state.py run` (`--set <run_id>`, `--terminal <handle>`) |
| handled log | `~/.claude/pipeline/handled.jsonl`: one `started` and one `answered` line per message, written only with `state.py handled start|answer` |
| scan floor | `~/.claude/pipeline/scan.json`, moved only by `coord.py seed|advance` |
| notices | `~/.claude/pipeline/notices.jsonl`, written with `state.py notice add`, read with `notice list`, cleared with `notice clear` |
| notes | `~/.claude/pipeline/coordinator-notes.md`, `state.py note add "<line>"` / `note show`; a `SessionStart` compact hook prints them after `/compact` |
| heartbeat | `~/.claude/pipeline/heartbeat`, written by `coord.py wait` each time the wait is armed; the watchdog reads it |
| spec | `<repo>/docs/superpowers/specs/YYYY-MM-DD-<id>-<slug>-design.md`; from step 5 on, the same relative path in the worktree |
| plan | `<repo>/docs/superpowers/plans/YYYY-MM-DD-<id>-<slug>.md`; from step 5 on, the same relative path in the worktree |
| preparation (plan mode) | `<repo>/<prep_dir>/`: `spec.md` + `plan.html`, committed on the current branch; replaces the spec and plan rows above. `prep_dir` per Plan mode, Folder |
| state (git-free) | `~/.claude/pipeline/<repo-basename>/<id>.json`, written only with `python3 -I ${CLAUDE_PLUGIN_ROOT}/scripts/state.py` (`new`, `set`, `done`, `abort`, `show`, `list`, `run`, `owner`) |
| git, file and PR steps | `python3 -I ${CLAUDE_PLUGIN_ROOT}/scripts/mission_ops.py <step> <repo-basename> <id>`: it touches only that mission's repo, worktree, branch and files. Never raw `git`, `cp`, `rm`, `mv` or `sed` |
| worktree | `orca worktree create --repo <selector> --name <id> --base-branch <base> --no-parent`; branch `feature/<id>-<slug>` |

## Loop

1. **Intake.** `/pipeline` with no arguments starts no mission: run Binding (below), which
   also re-arms watchers and recovers open asks, then `coord.py scan` (Waiting), arm the wait
   and print status in the terminal (the Outside asks status contents; there is no message to
   reply to). With a mission: the mission's repo is required (a path or an Orca repo selector,
   in the arguments or the ask); it must be in `orca repo list --json`, which gives its
   absolute path `<repo>` (and a selector for `orca worktree create`). No repo, or one not in
   that list → ask for a registered repo and create no mission. Get the ticket text (orca-linear skill if it is a Linear id). Parse `--base
   <branch>` from the arguments (default: the repo's default branch).
   `orca status --json`, then **Binding** (below) → `<shared>`. Then
   `state.py new <repo-basename> <id> ... --repo <repo> --base-branch <base> --run-id <shared>`, then
   write `mission.md` with `state.py file write <repo-basename> <id> mission.md` (the text on
   stdin), then `mission_ops.py owner-repo <repo>` → `state.py set ... owner_repo=<owner/repo>`.
   `--plan-only` in the arguments (or `/pipeplan`) → **Plan mode** (below): pick `prep_dir`
   (Plan mode, Folder), then `state.py set ... mode=plan prep_dir=<rel>`.
   Open the board: `/pboard`. No mission creates its own Run.

   **Binding** (on every session start, live worker or not; again only on the user's word):
   1. `state.py run --terminal $ORCA_TERMINAL_HANDLE`, first thing (the watchdog may already
      have saved it from the launch receipt; this overwrites it). Then `state.py run` → saved
      id. Non-zero exit: tell the user the path and stop; no wait is possible without a Run.
   2. Saved id and `run-current` already shows it → bound.
   3. Saved id → `run-show --id <id>`. Found → `run-use --id <id>`; any `run-use` error: tell
      the user the code and stop. `error.code` `run_not_found` → step 4. Any other `run-show`
      error: tell the user the code and stop. Never create a new Run silently.
   4. No saved id, or `run_not_found` → `run-create --objective "pipeline coordinator"`, then
      `state.py run --set <run_id>`.
   5. `coord.py seed --run <shared>`, every Binding. It seeds the scan floor only for a Run
      that has none yet (cutover, or a Run created in step 4), so questions an old session
      already read are not run again. Exit 3 with "already seeded" for this Run is normal; any
      other failure → `state.py notice add`.
   6. `state.py note show` (pending decisions, recent answers) and `state.py handled open`:
      every message with `started` and no `answered` goes through Recovery (Waiting).
   7. Re-arm watchers for every open mission (`state.py list`, then `state.py show`): stage
      `pr` with no greptile reviewer started yet → PR older than 5 min: start the greptile
      reviewer now; else arm `mission_ops.py greptile-delay` with `--seconds` = the time left.
      Stage `pr` or `ready` → arm `mission_ops.py merge-watch`.
   Every "stop" and every "tell the user" in Binding is also a `state.py notice add`.
2. **Read.** Pick 1 to 4 reader angles from the mission text (UI, data, patterns, tests). Start
   all readers in one wave, `--worktree path:<repo>`, arm the wait if none is running (Waiting) and end the turn. On
   each `worker_done` record the path and release that reader. Continue when every reader is
   released.
3. **Spec.** Start the senior with mission + readings paths and the spec destination (`mode=plan`:
   `<repo>/<prep_dir>/spec.md`). Rename its
   terminal `senior <id>`. Set `stages.spec.status=waiting_user`, `note="brainstorm with senior"`, `attention.terminal=<h>`, `attention.reason="brainstorm with senior"`, and tell the user `orca terminal switch --terminal <h>`, arm the wait if none is running and end the turn. On `worker_done` record the spec path, set `attention=null`, and close the senior's terminal (release, then `terminal close` on `retained`). `mode=plan` and the
   spec is outside `<prep_dir>` → Plan mode, Switch.
4. **Plan.** Start the planner with the spec path and plan destination (`mode=plan`: roles.md
   "planner (plan only)", destination `<repo>/<prep_dir>/plan.html`, and `stages.plan.plan_only_ran=true` in the `set` that records the receipt), arm the wait if none is running. On `worker_done` parse
   the body line into `stages.plan.tasks`, `stages.plan.parallel`; if `spec-is-plan: yes`, the plan
   path is the spec path. Release the planner. Then `state.py show` the mission: `mode=plan` →
   **Plan mode**: spec and plan both inside `<prep_dir>` → Cleanup (Plan mode, Switch), then P1;
   otherwise Switch. Never step 5.
5. **Worktree.** Ticket first (skip with no ticket): `orca linear issue <TICKET> --json`; if the
   state `type` is `triage`, `backlog` or `unstarted`, `orca linear status set <TICKET> --to
   "In Progress" --json`, `events+="ticket In Progress"`. A `started` or later state stays as it
   is. On `linear_invalid_state` leave it and tell the user; any other Linear error: follow the
   orca-linear Errors rules once, then tell the user. A ticket step never blocks the worktree. Then
   `orca worktree create --repo <selector> --name <id> --base-branch <base> --no-parent --json`
   → path. Record it first: `state.py set ... stages.worktree.path=<path>
   stages.worktree.branch=feature/<id>-<slug>`. Then `mission_ops.py docs-commit <repo-basename>
   <id> --scope <scope>`: it creates the branch, copies spec and plan to the same relative
   paths, commits `#<TICKET> docs(<scope>): add spec and plan`, and only after that commit
   removes the untracked spec and plan (one file when `spec-is-plan: yes`) from `<repo>`. It
   prints `{"kept": [...], "removed": [...]}`; tell the user every `kept` path (tracked, left in
   `<repo>`). Non-zero exit: nothing was removed; tell the user the error and wait for their
   word. Then `state.py set ... stages.spec.path=<worktree>/<rel> stages.plan.path=<worktree>/<rel>
   events+="moved spec and plan to worktree"`; steps 6 to 8 pass these worktree paths. Confirm no Dispatch of this mission is still reclaimable: `worker-show --dispatch <id>`
   for each id in its `dispatches`; release anything still reclaimable.
   Other missions' workers on the shared Run are never touched.
6. **Build.** `parallel: no` → one implementer, task 1; on `succeeded` reuse its terminal
   (`--terminal <handle>`) for task 2, and so on. `parallel: yes` → one implementer per task in one
   wave, all `--worktree name:<id>`. Arm the wait after every start if none is running. Update `stages.build.done` after each. Release an
   implementer when its last task `succeeded` (parallel: each on its own `worker_done`; serial:
   after task N). A `failed` outcome stops the build and keeps that terminal open: set `note`
   and `attention.terminal=<handle>`, tell the user the handle, wait for their word.
7. **Review.** When `done == tasks`, start the reviewer in the worktree (round 1; report
   `review.md`), `stages.review.rounds=1`, arm the wait if none is running. Act on the first word of its body:
   - `APPROVED` → release the reviewer, `stages.review.status=done`, go to step 8. The reviewer
     has written `pr-body.md`; you pass its path on, you do not read it.
   - `FIX:` → release the reviewer; start a fresh fix-round implementer (roles.md "implementer (fix
     round)", `--worktree name:<id> --agent claude --model opus --effort low`; the build
     implementer's terminal is already released), arm the wait if none is running. On
     `succeeded` release it and start the reviewer again (round N+1, report `review-N+1.md`,
     previous reports listed). At most **2 fix rounds**: a third `FIX:` is handled as
     `NEEDS_USER` with `note="review: 2 fix rounds did not converge"`.
   - `NEEDS_USER:` → `stages.review.status=waiting_user attention.terminal=<handle>
     attention.reason="<reason>"`, keep the reviewer's terminal, tell the user its handle and the
     one-line reason, end the turn. The user decides; you do not dispatch a fix unasked. When
     the user gives their decisions (in chat, or relayed by the reviewer as a `status` message),
     release and close the reviewer, start a fix-round implementer with the decisions, then
     re-review as above (this round does not count toward the 2-round cap).
8. **PR.** `stage=pr stages.pr.status=active note="opening PR"`.
   `mission_ops.py push <repo-basename> <id>` (mission branch only); split the body without
   reading it: `mission_ops.py pr-split <repo-basename> <id> --scope <scope>` prints the title
   (it already falls back to `#<TICKET> feat(<scope>): <mission title>` when the first line is
   empty or longer than 70 characters). Then `gh pr create --repo <owner_repo> --base <base>
   --head <branch> --title "<printed title>" --body-file <files>/pr-body-rest.md`. On a GitHub "Something went
   wrong" error, `gh pr list --repo <owner_repo> --head <branch> --state all` first and retry
   only if it is empty. Record `stages.pr.number`, `stages.pr.url`,
   `note="PR #<n> open; Greptile check in 5 min"`. Then, in one response, arm two background
   commands: the Greptile delay (`mission_ops.py greptile-delay`) and the merge watcher
   (`mission_ops.py merge-watch`; orca-commands.md Watchers). This mission needs no Orca wait until the greptile reviewer starts. The pipeline opens the PR itself: the user's request to run
   the mission is the authorisation to push this branch and open this one PR; nothing else is
   ever pushed.
   - When the delay wakes you: start the greptile reviewer (roles.md), arm the wait if none is running.
     `GREPTILE_OK` → release it, `stages.pr.greptile=<score>`, `stage=ready
     stages.pr.status=done note="ready: PR #<n> open, Greptile <score>; closes on merge"`.
     `NEEDS_USER:` → `stages.pr.status=waiting_user attention.terminal=<handle>
     attention.reason="Greptile <score>: <line>"`, keep its terminal, tell the user the handle,
     the score and the one line. The user decides whether to fix. On their word: release and close the greptile
     reviewer's terminal, dispatch a fix-round implementer with the Greptile report, on
     `succeeded` release it and `mission_ops.py push <repo-basename> <id>` (same PR), then `attention=null
     stage=ready stages.pr.status=done`. If the user declines: release and close the greptile
     terminal, `attention=null stage=ready stages.pr.status=done`.
   - When the merge watcher wakes you with `MERGED`: run **Finish** (step 9) with `--reason
     "MERGED into <base>: PR #<n> (<sha>, <mergedAt>)"`, tell the user. `CLOSED` without merge: `note="PR #<n> closed
     unmerged"`, `attention=null`, tell the user and wait for their word. Exit 2 (6 h without a
     result): re-arm the watcher.
9. **Close.** A `ready` mission stays on the board until its PR is merged. The merge watcher
   normally closes it; whenever the user says a mission is done or asks where missions stand,
   also run for every `pr`/`ready` mission:
   `gh pr list --repo <owner_repo> --head <branch> --state merged --json number,mergeCommit,mergedAt`. A merged PR, or the user's word, → **Finish** with
   `--reason "MERGED into <base>: PR #<n> (<sha>, <mergedAt>)"` (or `--reason "user: <their words>"`).
   **Finish**, in this order:
   1. Release any worker the mission still holds: `worker-show --dispatch <id>` for each id in
      its `dispatches`, release what is still reclaimable (`terminal close` on `retained`); stop
      its watchers (`TaskStop`).
   2. Ticket (skip with no ticket): `orca linear issue <TICKET> --json`; only when the state name
      is `In Progress`, `orca linear status set <TICKET> --to "Dev Complete" --json`,
      `events+="ticket Dev Complete"`. Any other state stays as it is; tell the user its name. On
      `linear_invalid_state` leave it and tell the user; any other Linear error: follow the
      orca-linear Errors rules once, then tell the user. A ticket step never blocks Finish.
   3. `orca worktree rm --worktree name:<id> --json`, never `--force`. Orca also deletes the
      local branch when it can prove it merged; otherwise the branch stays. On failure (e.g.
      uncommitted files) keep the worktree, add `; worktree kept: <error.code>` to the reason
      (the code only, no message text) and tell the user the full error.
   4. `state.py done <repo-basename> <id> --reason "<reason>"`. `done` hides the row.
10. **Abort** (only when the user says stop). Release every worker of the mission: for each
   id in its `dispatches`, `worker-show --dispatch <id>`, then `worker-release`, or
   `worker-stop` then `worker-abandon` when stop fails (active workers too), stop its
   watchers (`TaskStop`), then `state.py abort <repo-basename> <id> --reason "<one line>"`.
   Tell the user what was left behind: untracked spec/plan files (if step 5 did not remove them), a worktree,
   a branch, an open PR. You delete nothing.

State vocabulary: `stage` is one of `read spec plan worktree build review pr ready done aborted`
(`pr` = PR open, Greptile check running or waiting on the user; `ready` = Greptile done,
waiting for the merge; `done` and `aborted` are terminal: the board hides them and stops
auto-opening); every
`stages.<name>.status` is one of `pending active waiting_user done failed`. Create with
`state.py new <repo-basename> <id> --ticket <TICKET> --title "<title>" --repo <repo> --base-branch <base> --run-id <shared>`.
Every stage change is one `state.py set <repo-basename> <id> stage=<name> stages.<name>.status=<status> note="<board line>" events+="<what happened>"`,
plus the ids and paths the receipt gave (`dispatches+=`, `settled+=`, `stages.spec.path=`, `stages.build.workers+=`,
`stages.pr.number=`). The board polls the file; nothing else updates it.

**Attention = a terminal the user should open.** Whenever you tell the user a terminal handle
(senior brainstorm, implementer `failed`, reviewer or greptile `NEEDS_USER`, an `escalation`),
set it in the same `state.py set`: `attention.terminal=<handle> attention.reason="<one line>"`.
The board turns that into a switch button (hotkeys 1..9 down the switch rows) that runs `orca terminal
switch`. Clear it with `attention=null` in the `set` that records the stage moving on or the
user's answer.

**Every "tell the user" is also a notice.** The coordinator terminal may have nobody watching
it, so each time this skill says "tell the user", also run `state.py notice add --kind <kind>
--mission <id> --line "<the one line>"` (no `--mission` when no mission is involved). This
covers dropped messages, Binding failures, `consumer_fenced`, Linear errors and kept files or
worktrees. The board shows open notices; every status reply lists them; clear one with
`state.py notice clear <id>` only when an ask or the user says so.

## Plan mode

`mode=plan` runs steps 1 to 4 only. The output is `spec.md` + `plan.html` in `<repo>/<prep_dir>`,
committed on the current branch of `<repo>`. No worktree, no build, no PR, no ticket status
change, nothing pushed. The user's request for plan mode is the authorisation for this one
commit.

- **Folder.** `prep_dir` is `docs/preparation/<id>-<slug>` (no ticket: `docs/preparation/<id>`,
  the id already holds the slug). Pick it once, store it with `state.py set ... prep_dir=<rel>`,
  and build every plan-mode path from the stored value, never from the slug again. Before
  storing it, look for `<repo>/docs/preparation/<id>`, and with a ticket also
  `<repo>/docs/preparation/<id>-*` (a no-ticket id checks the exact folder only). One
  exists → tell the user its path and the two choices: reuse it as `prep_dir` (its `spec.md` and
  `plan.html` are replaced and the commit updates them), or Abort. Wait for their word.
- **P1. Commit.** Both `stages.spec.path` and `stages.plan.path` must be under
  `<repo>/<prep_dir>`; otherwise go to Switch, never commit a full-flow path.
  `mission_ops.py prep-commit <repo-basename> <id> --scope <scope>` prints `<sha>`. It refuses
  (exit 3) on a path outside `<prep_dir>`, a detached HEAD, or a merge, cherry-pick, revert or
  rebase in progress; otherwise it commits only `<spec> <plan>` (`#<TICKET> docs(<scope>): add
  spec and plan`, no ticket: no `#<TICKET> `), so the user's other staged work stays out. Never
  `--no-verify`, never `--amend`. On any refusal or failure (e.g. a pre-commit hook) both files
  are unstaged again; `stages.plan.status=failed note="commit: <one line>"`, tell the user the
  full error, wait for their word. On it: `mission_ops.py prep-status <repo-basename> <id>`
  exit 0 prints the sha the user committed: that is `<sha>`, go to P2. Exit 1 (not committed)
  → run P1 again.
- **P2. Finish.** Release any worker the mission still holds (Finish step 1), then
  `state.py set ... stages.plan.status=done attention=null` and
  `state.py done <repo-basename> <id> --reason "planned: <sha> <prep_dir>/"`. Skip Finish steps
  2 and 3.
- **Switch.** When the user says "switch <id> to plan mode": `state.py show` it. Stage `worktree`
  or later → refuse, tell the user Abort is the way out. Stage `read`, `spec` or `plan` → pick
  `prep_dir` as in Folder, then `state.py set ... mode=plan prep_dir=<rel>
  events+="switched to plan mode"` (when step 3 or 4 routes back here, `mode` and `prep_dir`
  are already stored: skip this). Apply these in order:
  1. Spec. Already inside `<prep_dir>` → go to 2. Senior not started → step 3 as written for `mode=plan`. Senior running → wait for its
     `worker_done` (step 3), then move. Senior done → move, but only while no planner of this
     mission is running; a running planner reads the spec, so wait for its `worker_done` first. Move =
     `mission_ops.py move-doc <repo-basename> <id> --to <prep_dir>/spec.md`, which prints
     `{"path", "action"}`: `moved` (was untracked) or `copied` (tracked: tell the user); then
     `stages.spec.path=<path>`.
  2. Plan, only after the spec sits in `<prep_dir>`. Plan already inside `<prep_dir>` → Cleanup,
     then P1. Planner not started → step 4 as written for `mode=plan`. Planner running → wait for
     its `worker_done` (step 4 routes back here). Planner done with a plan outside `<prep_dir>`:
     `stages.plan.plan_only_ran` is true → do not start another planner;
     `stages.plan.status=failed note="plan-only planner wrote outside <prep_dir>"`, tell the user,
     wait for their word. Otherwise `stages.plan.old_path=<its plan path>` (empty when
     `spec-is-plan: yes`: that path was the spec, already moved), then start "planner (plan
     only)" with `{existing_plan}` = the old path (empty when `spec-is-plan: yes`) and
     `stages.plan.plan_only_ran=true`; its `worker_done` goes through step 4.
  - **Cleanup.** `stages.plan.old_path` set → `mission_ops.py remove-old-plan <repo-basename>
    <id>`: untracked → removed; tracked → listed under `kept`, tell the user; then
    `stages.plan.old_path=""`. Not set → nothing.
  - Never switch back to the full flow.
- **Abort** in plan mode leaves `<prep_dir>` behind, untracked or modified; tell the user.

## Waiting

Never block the turn on a worker. Every mission and every outside ask shares one Run
(`<shared>`, from Binding) and one wait. The wait is one **background** Bash call
(`run_in_background: true`) that writes the heartbeat, then exits when a batch lands or the
timeout ends; the harness wakes you when it exits:

```text
python3 -I ${CLAUDE_PLUGIN_ROOT}/scripts/coord.py wait --run <shared> --out <scratchpad>/pipeline/inbox.json
```

Then end the turn. On the wake:

1. Background task exit 0 → read `inbox.json` and route every message in the batch, oldest
   first (Routing). Non-zero exit → nothing was written to `inbox.json`: read that background
   task's output, `state.py notice add --kind wait --line "<code and one line>"`, and follow
   the `consumer_fenced` rule below when the code says so (never rebind on your own).
2. `coord.py scan --run <shared>` → JSON list of inbox rows above the floor with no `answered`
   line, oldest first. Route each (Routing). Exit 5: the window was too short (the script has
   written the notice); run it once more with `--limit 500`. Exit 3 (scan file missing, bad,
   or for another Run): notice, tell the user, skip the scan; the next Binding seeds it.
3. `coord.py advance --run <shared>` moves the floor up as far as every row is `answered`
   (exit 5: window too short, floor kept; exit 3: as above).
4. Arm the wait again. Always, also after a timeout or an empty batch.

**Routing**, for each message, in this order. The message record (from the `check --full`
batch or a `scan` row) carries `id`, `sequence`, `type`, `from_handle` and `payload`:

1. `state.py handled get <id> --seq <sequence>` prints `answered` → skip it: no action, no
   notice (answered is sticky, and a `sequence` at or below the scan floor counts as
   answered, so a message the scan already handled is not run again when the wait delivers it).
2. Prints `started` → **Recovery** (below).
3. Otherwise `state.py handled start <id> --seq <sequence> --type <type> --from <from_handle>
   --kind outside|mission --summary "<one line>"` **before any action** (`--seq` is the
   record's `sequence`; exit 3 = refused (no or bad `sequence`, or at or below the floor):
   no action and no notice, leave the message to the scan). Then take the
   Dispatch id from `JSON.parse(message.payload).dispatchId` (never `from_handle`):
   - no `dispatchId` (or payload missing / not JSON), type `question` → **outside ask**
     (Outside asks); any other type → notice, no action.
   - `dispatchId` → `state.py owner <dispatchId>`: exit 0 `… live` → act on that mission as
     the Loop says; exit 0 `… settled` → a re-sent message, no action; exit 3 (no owner), 4
     or any other code → notice with the message type, Dispatch id and task title, no action.
     A late message from a worker of a done or aborted mission never gets the user's
     authority.
4. After the action (and the `reply` for an outside ask): `state.py handled answer <id>
   --summary "<one line>"`. Every message ends `answered`, also those that only got a
   notice; otherwise the floor never moves past it.

**Recovery** (routing step 2, and at Binding for every line `state.py handled open` prints):
check whether the action happened (e.g. `state.py show`, `state.py notice list`). A
`kind=mission` line: re-check the mission state, finish the Loop step if it did not happen,
no reply. A `kind=outside` line: done → reply with the result; not done → do it now, then
reply; cannot tell (free-text action with no trace) → reply "I may have done this before a
restart; check <what>". Then `handled answer`. A crash between `reply` and `answered` can send a second answer; that is accepted.

Rules:

- **Never two waits.** One open `coord.py wait` at a time; a second consumer races on the
  same FIFO. Every "arm the wait" in the Loop means "if none is running". Check first:
  `pgrep -f "coord.py wait --run <shared>"`, exit 0 = one is running. Any read you need
  between wakes is `--peek`. Inside a wake the old wait has exited: arm it once, at step 4.
- **The wait is always armed.** Before any turn ends, a wait is running, whether or not any
  mission is open or has a live worker. The two exceptions are a Binding failure (no Run)
  and `consumer_fenced` (another terminal holds the Run): no wait, and a notice.
- **Live worker** = a Dispatch id in an open mission's `dispatches` that is not in its
  `settled` (`state.py show` on each open mission from `state.py list`).
- **A stop is per mission.** "Stop", "wait for their word" and "end the turn" in the Loop
  (implementer `failed`, `NEEDS_USER`, escalation, senior brainstorm, PR closed unmerged) hold
  that mission only.
- **`consumer_fenced`** on `check`, `coord.py wait` or `worker-start`: another terminal took
  the Run. Tell the user (and a notice); never rebind on your own (two sessions would fence
  each other over and over). Rebind with Binding only on the user's word.
- A wake with an empty result or a timeout is a checkpoint, not a failure: re-arm. Three empty
  wakes in a row, and at least one mission open: `worker-list --run <shared> --include-remote
  --json`, following `page.nextCursor` while `page.hasMore`; map each row with `state.py owner
  <row.dispatchId>` and follow `projection.nextAction` only on `live` rows. No open mission:
  skip it.
- A wake is not the user's reply. It can land while they type in a worker's terminal; their
  word still arrives as a user message, a `status` message the worker relays, or an outside ask.
- Watchers (Greptile delay, merge watcher) are background Bash too and run beside the wait;
  they do not touch the Orca FIFO. No `timeout` binary exists on this Mac: a `timeout gh ...`
  fails silently and the watcher never fires.
- A foreground wait is wrong twice: the harness kills a foreground command at 10 min (the wait
  asks for 15), and you cannot answer the user or update the board while it runs.

## Outside asks

An outside ask is a `question` with no `dispatchId`, sent by a tool or another Claude session
with `orca orchestration send --to run:<shared> --type question`. It is free text: read it
and do what it asks, as if the user typed it, then `orca orchestration reply --id <id>
--body "<answer>" --json` (Orca adds `Re: <subject>`), then `handled answer`.

- **Same wake.** Every outside ask is answered in the wake that routed it. A long request
  ("start X and tell me when the spec is done") gets an immediate reply ("started X; ask for
  status") and is never held open.
- **Predefined actions:** status of all missions; details of one mission; start a mission
  (same as `/pipeline <args>`, repo required, Intake); stop a mission (Abort). Anything else is
  handled like a request the user types.
- **Status reply** lists every open mission (id, stage, note), every pending decision (mission
  id, `attention.reason`, and the report path the decider needs, e.g. `<files>/review.md` or
  `<files>/greptile-review.md`), the senior's terminal handle for a brainstorm (the tool talks
  to the senior directly; you do not relay it), and every open notice (`state.py notice list`).
- **Decisions.** A later ask can give the user's word on `NEEDS_USER` (reviewer, Greptile), fix
  or decline, implementer `failed`, `escalation`, an existing plan-mode folder, or Abort. Act on
  it exactly as on the user's chat reply. An ask is also the user's approval for a push, a PR
  and a Linear or GitHub call, the same way "run this mission" is.
- When an ask leads to a decision or a pending item, `state.py note add "<one line>"` before
  `handled answer`.
- Never answer an outside ask with "Decide yourself…"; that is for mission workers only.

## Worker questions

A `question` from a reader, planner or implementer: reply `Decide yourself and record the
assumption in your report.` An `escalation`: set `note` and `attention.terminal=<handle>`, tell
the user the handle, wait (that mission only; Waiting); clear `attention` when they have answered. The
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
- "This ask has no owner, I'll skip it." → A `question` with no `dispatchId` is an outside ask; answer it (Outside asks).
- "I'll write mission.md with the Write tool." → `state.py file write`; the Write tool prompts under `~/.claude/pipeline` and stalls the session.

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
