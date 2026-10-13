# Shared Run for the pipeline coordinator — design

Date: 2026-10-14. Status: approved in chat; revised after hawkeye review; waiting for spec review.

## Problem

Today every mission creates its own Orca Run (`SKILL.md` step 1, `run-create`). A coordinator
terminal is bound to one Run at a time, and only one `check --wait` can be live per bound Run
(`SKILL.md` Waiting: "One bound Run per coordinator terminal"). With two live missions, the
second mission's `worker_done`, `question` and `escalation` messages sit in their Run until
Orca's best-effort nudge reaches the coordinator and it switches with `run-use`. The user sees
one mission's messages wait while they answer another mission.

## Goal

One coordinator session dispatches and manages several missions. Every message from every
mission reaches the coordinator through one wait, with no `run-use` switching. A restarted
coordinator rejoins the same Run.

Out of scope: the coordinator still handles wakes one at a time; a wake that lands mid-turn is
handled when the turn ends. Two coordinator sessions live at once is not supported (user
decision, 2026-10-14).

## Facts this design rests on

| Fact | Label | Source |
|---|---|---|
| A Run is a namespace and home inbox; it never schedules or places workers | VERIFIED | `orca orchestration run-create --help`; `orca skills get orchestration` line 48 |
| `check --wait` returns the bound Run's whole FIFO batch, not filtered by type | VERIFIED | `orca orchestration check --help` Notes |
| A bound Run replays the same Delivery until `--ack` | VERIFIED | `orca orchestration check --help` Notes |
| `check --ack <id>` without `--wait` is still a consuming check (returns the next batch) | VERIFIED | `check --help`: "--ack: acknowledge the prior whole batch before checking/waiting"; "default: return the bound Run's oldest unacknowledged FIFO batch" |
| `worker-start` accepts `--run <run_id>` | VERIFIED | `orca orchestration worker-start --help` |
| `run-show --id <id>` exists and is read-only | VERIFIED | `orca orchestration run-show --help` |
| `worker-list` has no filter by Dispatch or Task (`--run`, `--terminal-state`, `--include-remote`, `--cursor`, `--limit` only) | VERIFIED | `orca orchestration worker-list --help` |
| `worker-show --dispatch <id>` inspects one Dispatch | VERIFIED | `orca orchestration worker-show --help` |
| Waiting on a Run without binding to it is not supported | INFERRED | `check --help` documents only the bound Run; `orca-commands.md` `consumer_fenced` note |
| Workers in different worktrees and repos can share one Run | INFERRED | follows from "never places workers"; live test T1 |
| After `run-use` from a new terminal, unacked messages of the Run replay | INFERRED | follows from the replay rule; live test T1 |
| `question` and `escalation` messages carry the sender's Dispatch id | UNKNOWN | live test T1 |
| No mission is open now, so no migration | VERIFIED | `state.py list` printed no rows on 2026-10-14 |

## Design

### 1. Saved Run

- One file per machine: `~/.claude/pipeline/coordinator.json`, shape
  `{"run_id": "<id>", "created": "<iso>", "updated": "<iso>"}`.
- It sits next to the repo folders under `ROOT`. `cmd_list` reads only sub-folders of `ROOT`
  (`state.py` `cmd_list`) and the board skips non-folders (`register.tsx`, `repo.kind !== 'dir'`),
  so the file never shows up as a mission.
- Only `state.py` touches it:
  - `state.py run` prints the saved `run_id`, or an empty line when the file is missing. Exit 0
    both ways. A file that exists but does not parse, or has no non-empty string `run_id`:
    exit 3 with the path on stderr.
  - `state.py run --set <run_id>` creates `ROOT` if needed and writes the file atomically (same
    temp-file + `os.replace` as `save`). `created` is kept when the file exists; `run_id` and
    `updated` change. A file that exists but does not parse: exit 3, file unchanged.

### 2. Binding

**When:** on the coordinator's first turn of a session that will start a worker or arm a wait:
the first `/pipeline` (before `state.py new`), or the first turn after a restart in which any
open mission has a live worker (`/pipeline`, a status question). Binding runs at most once per
session unless the user asks.

**Steps:**

1. `state.py run` → saved id. Non-zero exit: tell the user the path and stop (no wait is
   possible without a Run).
2. Saved id present → `orca orchestration run-current --json`. Already bound to it: done.
3. Saved id present → `orca orchestration run-show --id <id> --json`.
   - Found → `orca orchestration run-use --id <id> --json`. Success: done. Any error: tell the
     user the error code and stop. Never create a new Run silently.
   - Not found → step 4. (Exact not-found code recorded in T1.)
   - Any other `run-show` error: tell the user the code and stop.
4. No saved id, or not found → `orca orchestration run-create --objective "pipeline coordinator" --json`,
   then `state.py run --set <run_id>`.

Step 1 of the Loop becomes: get the ticket text, parse `--base`, write `mission.md`,
**binding**, then `state.py new … --run-id <shared>`, then `state.py set … owner_repo=…`, then
`/pboard`. The per-mission `run-create` is removed.

### 3. Mission ↔ Dispatch

- `state.py new` takes a required `--run-id <id>` and writes `"run_id": <id>`,
  `"dispatches": []`, `"settled": []`.
- Every `worker-start` (readers, senior, planner, implementers, reviewer, fix rounds, greptile
  reviewer) passes `--run <shared>`. After each receipt:
  `state.py set … dispatches+=<dispatch_id>` in the same `set` that records the role's worker.
  Reusing a terminal (`--terminal <handle>`, serial build) is a new Dispatch; its id is appended
  too.
- When the coordinator accepts a `worker_done` for a Dispatch: `settled+=<dispatch_id>` in the
  same `set` that records the outcome.
- `state.py owner <dispatch_id>` scans missions that are not `done`/`aborted` in every repo
  folder; it reads `dispatches` and `settled` with `.get(…, [])`.

  | Exit | Output | Meaning |
  |---|---|---|
  | 0 | `<repo-slug> <id> live` | owned, not yet settled |
  | 0 | `<repo-slug> <id> settled` | owned, already settled (a replayed or re-sent message) |
  | 3 | nothing | no open mission lists the id |
  | 4 | one line per match | two open missions list the id (coordinator bug) |
  | other (1, 2, …) | Python / argparse error | `owner` failed; treat as unknown |

- `dispatches+=` and `settled+=` store the id as given: these two keys skip `parse_value`, so a
  number-like id stays a string.

### 4. One wait for the session

- One background wait on the shared Run, output to `<scratchpad>/pipeline/inbox.json` (moved
  from `<scratchpad>/pipeline/<id>/inbox.json`):
  `orca orchestration check --run <shared> --wait --types "worker_done,escalation,question" --timeout-ms 900000 --json > <scratchpad>/pipeline/inbox.json`
- **Never two waits.** Every "arm the wait" in the Loop becomes "arm the wait if none is
  running". The check is read-only and survives compaction:
  `pgrep -f "orchestration check --run <shared> .*--wait"`; exit 0 means one is running.
- **On a wake,** for every message in the batch, by Dispatch id → `state.py owner`:
  - `live` → act on that mission exactly as today.
  - `settled` → replayed or re-sent; take no action.
  - exit 3 (no owner) → take no action, and tell the user the message type, Dispatch id and
    task title in one line. A `question` with no owner leaves a worker blocked, so the user
    must hear about it.
  - exit 4 or any other code → tell the user; take no action for that message. Still ack the
    batch (below), so other missions keep moving.
  - Then ack and re-arm in one call: `check --run <shared> --ack <delivery_id> --wait …`.
- **The wait outlives any one mission's stop.** "Stop", "wait for their word" and "end the
  turn" in the Loop (implementer `failed`, `NEEDS_USER`, escalation, senior brainstorm) apply to
  that mission only. Before any turn ends, the current batch is acked and a wait is running,
  while any open mission has a live worker. The only exception is a binding failure (section 2),
  where no wait is possible.
- **Unarmed gap.** When a wait times out (no batch, nothing to ack) and no open mission has a
  live worker, do not re-arm. The next `worker-start` (any mission) arms it again ("if none is
  running"). Missions in `pr`/`ready` rely on their Bash watchers, not on the wait.
- **Three empty wakes in a row:** `worker-list --run <shared> --include-remote --json`,
  following `page.nextCursor` while `page.hasMore`; map each row to a mission with
  `state.py owner` (by the row's Dispatch id; field name from T1) and act only on `live` rows.

Removed from `SKILL.md` Waiting: the "two missions live → keep the wait on the Run with a
worker, `run-use` the other on a nudge" rule.

### 5. `consumer_fenced`

- On `check` or `worker-start`: another terminal has taken the Run. Tell the user and do not
  rebind on your own (two sessions would fence each other over and over). Rebind only on the
  user's word, with section 2.
- On `--ack` after a rebind (stale Delivery id): unchanged; run a plain consuming
  `check --run <shared>` (it replays the batch under a new Delivery id) and ack that.

### 6. Release, Finish, Abort

- Per-mission cleanup works on that mission's own Dispatches, not on `worker-list` rows:
  for each id in `dispatches`, `worker-show --dispatch <id> --json`, then release, stop or
  abandon as today. Replayed releases are safe (recovery-and-cleanup reference).
- Step 5 ("reclaimable must be empty") becomes: no Dispatch in the mission's `dispatches` is
  still reclaimable per `worker-show`.
- Abort loops over `dispatches` (active workers are not `reclaimable`, so a reclaimable filter
  would miss them).
- The shared Run is never closed by a mission.

## Files

| File | Change |
|---|---|
| `scripts/state.py` | `run` (get / `--set`), `owner`, `new --run-id` (required), `dispatches` + `settled` in `new`, `dispatches`/`settled` append skips `parse_value`; docstring lines |
| `scripts/state_test.py` | new; `unittest`, `ROOT` pointed at a temp folder |
| `skills/pipeline/SKILL.md` | Loop step 1 (binding before `new`, no per-mission `run-create`); every "arm the wait" (steps 2, 3, 4, 6, 7, 8 greptile) → "if none is running"; step 5 and Finish/Abort per-Dispatch cleanup; step 8 "No Orca wait is needed on this Run" line; Places (inbox path, `coordinator.json`, state commands); State vocabulary `run_id=` example; Waiting (section 4); Worker questions (stop is per mission) |
| `skills/pipeline/references/orca-commands.md` | binding block (`run-show`, `run-current`, `run-use`, `run-create` once); `--run <shared>` on every `worker-start` and `worker-list`; wait/ack path; `pgrep` check; `state.py owner`; remove the `inbox` "across runs" line; `consumer_fenced` checks (section 5); three-empty-waits paging |

Not touched: `types/index.d.ts` (the `Mission` type mirrors only what the board reads and has
no `run_id` today), `hooks/*`, `.claude-plugin/*`, `README.md`, `docs/plans/*`,
`references/roles.md`.

## Tests

Unit (`python3 -I -m unittest scripts/state_test.py`):

1. `run` with no file prints an empty line, exit 0.
2. `run --set A` then `run` prints `A`; `--set B` keeps `created`, changes `run_id`.
3. `run` and `run --set` with a corrupt `coordinator.json` exit 3; the file is unchanged.
4. `run` with a file lacking `run_id` exits 3.
5. `list` with `coordinator.json` present prints no extra row.
6. `new` without `--run-id` fails; with it writes `run_id`, `dispatches: []`, `settled: []`.
7. `owner` prints `<slug> <id> live` for a listed id, `settled` after `settled+=`; exit 3 for an
   unknown id.
8. `owner` skips a `done` / `aborted` mission that lists the id.
9. `owner` with two open missions listing one id exits 4 and prints both.
10. `owner` with one corrupt mission file next to a matching one: exits non-zero and not 0/3
    (never reports "no owner" on a crash).
11. `dispatches+=123` stores the string `"123"`.

Live (T1, needs the user's yes; creates a throwaway Run and two terminals, then releases them):

1. Terminal A: create a throwaway Run; start two Haiku workers on it with `--run` in two
   different worktrees; one wait. Record: both `worker_done` arrive through the one wait; the
   Dispatch id field in `worker_done`, `question` (one worker asks via `ask`) and in
   `worker-list` rows.
2. Leave one `worker_done` unacked. Terminal B: `run-use` onto the throwaway Run. Record whether
   `run-use` succeeds while A is live and whether B's consuming `check` replays the unacked
   message.
3. `run-show --id run_does_not_exist --json`: record the not-found code.
4. Release both workers.

If `question`/`escalation` lack a Dispatch id, the fallback is the task title
`<role> <mission-id>` for those types; section 3 is updated before implementation.

## Risks

- A second coordinator session that binds takes the Run and fences the first one's wait.
  Accepted by the user; section 5 stops the ping-pong.
- Orca's app shows every mission's Tasks under one Run. The board still shows one row per
  mission.
- Restart and scratchpad (outside this spec): the scratchpad is per session, so a restarted
  coordinator's `<scratchpad>/pipeline/<id>/…` paths (review reports, `pr-body.md`,
  `pr-final.json`) point to a new, empty folder. The coordinator should use the paths stored
  in the state file. Not changed here; noted for a follow-up.
