# Shared Run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One coordinator session runs every mission on one saved Orca Run, so one background wait
gets every mission's messages.

**Architecture:** `state.py` gains the saved-Run file (`run`), the Dispatch → mission lookup
(`owner`) and two per-mission lists (`dispatches`, `settled`). The skill docs (`SKILL.md`,
`orca-commands.md`) switch the coordinator from one Run per mission to binding once per
session, one wait, per-mission stops, and per-Dispatch cleanup.

**Tech Stack:** Python 3 stdlib (`state.py`, `unittest` via subprocess), Markdown skill docs.

**Spec:** `docs/superpowers/specs/2026-10-14-shared-run-design.md` (commit `60f8f3c`).

**Execution:** Native, in this session, on `main` (user's choice, 2026-10-14). One commit per
task. Never push. hawkeye reviews the whole change after Task 2.

## Global Constraints

- Saved Run file: `~/.claude/pipeline/coordinator.json`, shape `{"run_id", "created", "updated"}`.
- `state.py run` exit codes: 0 (id or empty line), 3 (corrupt file or no non-empty string `run_id`).
- `state.py owner` exit codes: 0 `<slug> <id> live|settled`, 3 none, 4 duplicate (one line each).
  Any other code means `owner` failed.
- `state.py new --run-id` is required.
- `dispatches+=` / `settled+=` store the raw string (no `parse_value`).
- Message Dispatch id = `JSON.parse(message.payload).dispatchId`, never `from_handle`.
- Run existence check: `run-show --id <id>`; not found = `error.code == "run_not_found"`.
- Every `worker-start` and `worker-list` carries `--run <shared>`.
- Do not touch: `types/index.d.ts`, `hooks/*`, `.claude-plugin/*`, `README.md`, `docs/plans/*`,
  `skills/pipeline/references/roles.md`.
- No refactor, rename or reformat outside the lines each task names.

## Review Focus

1. **Corrupt mission JSON during `owner`** → must not exit 3 ("no owner" would drop a live
   `worker_done`). Task 1 test `test_owner_corrupt_mission_is_not_no_owner`.
2. **Old mission file without `dispatches`/`settled`** (made before this change) → `owner`
   reads them with `.get(…, [])`, no crash. Task 1 test `test_owner_mission_without_lists`.
3. **`~/.claude/pipeline` does not exist yet** (fresh machine) → `run --set` creates it; `run`
   prints an empty line; `owner` exits 3. Task 1 tests `test_run_set_creates_root`,
   `test_owner_no_root`.
4. **`run --set` with an empty string** → refuse (exit 3), never save an empty `run_id`.
   Task 1 test `test_run_set_empty_refused`.
5. **A `.DS_Store` or other stray file under a repo folder or `ROOT`** → `list` and `owner` skip
   non-`.json` files and non-folders. Task 1 test `test_owner_skips_stray_files`.

---

## File map

| File | Task | Responsibility |
|---|---|---|
| `scripts/state.py` | 1 | `run`, `owner`, `new --run-id`, `dispatches`/`settled`, raw append, docstring |
| `scripts/state_test.py` (new) | 1 | CLI tests via `subprocess`, `HOME` pointed at a temp folder |
| `skills/pipeline/SKILL.md` | 2 | coordinator rules (spec sections 2–6) |
| `skills/pipeline/references/orca-commands.md` | 2 | exact commands for the new rules |

Task 2 depends on Task 1's command names and exit codes. No other ordering.

---

### Task 1: `state.py` — saved Run, owner lookup, dispatch lists

**Files:**
- Modify: `scripts/state.py` (docstring 3–18, `cmd_new` 67–89, `cmd_set` 92–110, `main` 157–176; new `cmd_run`, `cmd_owner`)
- Create: `scripts/state_test.py`

**Interfaces (Produces, used by Task 2 text):**
- `state.py run` → stdout `<run_id>\n` or `\n`; exit 0 / 3.
- `state.py run --set <run_id>` → stdout `<run_id>`; exit 0 / 3.
- `state.py owner <dispatch_id>` → see Global Constraints.
- `state.py new <slug> <id> --run-id <id> [--ticket --title --repo --base-branch]` → adds
  `"run_id"`, `"dispatches": []`, `"settled": []`.
- `state.py set <slug> <id> dispatches+=<id> settled+=<id>` → raw string append.

**Implementation notes (no full code):**
- `COORD = os.path.join(ROOT, "coordinator.json")`. Write with the same temp-file +
  `os.replace` pattern as `save`, after `os.makedirs(ROOT, exist_ok=True)`.
- `run`: missing file → print empty line, exit 0. Read errors (`ValueError`, `OSError`) or
  `run_id` not a non-empty `str` → stderr `bad coordinator file: <path>`, `sys.exit(3)`.
  `--set`: empty value → exit 3; existing file that does not parse → exit 3, unchanged;
  keep `created`, set `run_id`, `updated`.
- `owner`: iterate sub-folders of `ROOT` (same filter as `cmd_list`), `*.json` only; skip
  `stage` in `TERMINAL`; match on `dispatch_id in m.get("dispatches", [])`; status
  `settled` if in `m.get("settled", [])` else `live`. 0 matches → exit 3; >1 → print all,
  exit 4. Do NOT catch JSON errors: a crash exits 1 (traceback), which the coordinator reads
  as "owner failed".
- `cmd_set`: in the `+=` branch, `if key in ("dispatches", "settled"): val = raw`.
- `new`: `n.add_argument("--run-id", required=True)`.
- `run` subparser: `r.add_argument("--set", dest="set_id")`.

- [ ] **Step 1: Write the failing tests** in `scripts/state_test.py`. Each test runs
  `subprocess.run([sys.executable, "-I", STATE, ...], env={**os.environ, "HOME": tmp})`
  with a fresh `tempfile.TemporaryDirectory()` and asserts exit code + stdout/file content.
  Helper `mission(slug, mid, stage="read", dispatches=None, settled=None)` writes a mission
  JSON directly for owner tests. Tests:
  - `test_run_no_file_prints_empty` (spec test 1)
  - `test_run_set_then_get`, `test_run_set_keeps_created` (spec test 2)
  - `test_run_corrupt_file_exit3_unchanged`, `test_run_set_corrupt_file_exit3_unchanged` (3)
  - `test_run_file_without_run_id_exit3` (4)
  - `test_run_set_creates_root`, `test_run_set_empty_refused` (Review Focus 3, 4)
  - `test_list_ignores_coordinator_file` (5)
  - `test_new_requires_run_id`, `test_new_writes_run_id_and_lists` (6)
  - `test_owner_live_then_settled`, `test_owner_unknown_exit3` (7)
  - `test_owner_skips_done_and_aborted` (8)
  - `test_owner_duplicate_exit4_prints_both` (9)
  - `test_owner_corrupt_mission_is_not_no_owner` — exit code not in (0, 3) (10, Review Focus 1)
  - `test_append_dispatch_keeps_string` — `dispatches+=123` stores `"123"` (11)
  - `test_owner_mission_without_lists`, `test_owner_no_root`, `test_owner_skips_stray_files`
    (Review Focus 2, 3, 5)
- [ ] **Step 2: Run, expect failures:** `python3 -I -m unittest scripts/state_test.py -v`
  (from the repo root). Expected: errors on `run`/`owner`/`--run-id`.
- [ ] **Step 3: Implement** per the notes above; update the docstring with the three new usage
  lines and one line on exit codes.
- [ ] **Step 4: Run, expect pass:** same command; all tests PASS.
- [ ] **Step 5: Commit:** `git add scripts/state.py scripts/state_test.py` —
  "Add saved Run and Dispatch owner lookup to the mission state script".

---

### Task 2: Skill docs — bind once, one wait, per-mission stop, per-Dispatch cleanup

**Files:**
- Modify: `skills/pipeline/SKILL.md`
- Modify: `skills/pipeline/references/orca-commands.md`

**Interfaces (Consumes):** Task 1 commands and exit codes, exactly as named above.

**`SKILL.md` edits (by current line):**
- 44–52 Places: inbox row → `<scratchpad>/pipeline/inbox.json` (one per session; watcher files
  stay per mission); add row `saved Run | ~/.claude/pipeline/coordinator.json, only via
  state.py run`; state row command list adds `run`, `owner`.
- 57–60 step 1: order becomes ticket text → `--base` → `mission.md` → **Binding** (new
  subsection, spec section 2) → `state.py new … --run-id <shared>` → `owner_repo` → `/pboard`.
  Remove `run-create` / "store `run_id`".
- Steps 2, 3, 4, 6, 7, 8 (lines 62, 66, 67, 87, 92, 97, 120): every "arm the wait" →
  "arm the wait if none is running (Waiting)"; every `worker-start` records
  `dispatches+=<dispatchId>`; every accepted `worker_done` records `settled+=<dispatchId>`
  (one sentence near the Roles table, not repeated per step).
- 83–84 step 5: replace the `worker-list … reclaimable` check with the per-Dispatch check
  (spec section 6).
- 90, 103, 132 and Worker questions (escalation): add one rule in Waiting that a stop,
  "wait for their word" or "end the turn" applies to that mission only (spec section 4);
  these lines stay as they are.
- 117: "No Orca wait is needed on this Run until…" → "This mission needs no Orca wait until…".
- 140–157 Finish step 1 and Abort: release over the mission's `dispatches` with `worker-show`
  (spec section 6).
- 163–165 State vocabulary: `state.py new` example gains `--run-id <shared>`; `run_id=` →
  `dispatches+=`.
- 176–199 Waiting: rewrite to spec section 4 (one wait, `pgrep` check, wake handling by
  `owner` result, unarmed gap, three empty wakes with `--run` and paging). Remove the
  "One bound Run per coordinator terminal … nudge … `run-use`" bullet. Add the
  `consumer_fenced` rule (spec section 5): tell the user, never rebind on your own.

**`orca-commands.md` edits:**
- 8–9: binding block — `state.py run`, `run-current`, `run-show --id` (`run_not_found`),
  `run-use --id`, `run-create --objective "pipeline coordinator"`, `state.py run --set`.
- 12–41: add `--run <shared>` to every `worker-start`.
- 44–47: `<run_id>` → `<shared>`; wait output path; add the `pgrep` line and
  `state.py owner <payload.dispatchId>`; note `payload` is a JSON string.
- 48: remove the `inbox … across runs` line.
- 50–52: `worker-show`-per-Dispatch cleanup; `worker-list --run <shared>` kept for the
  three-empty-waits step only.
- 101–105: `consumer_fenced` on `check`/`worker-start` → tell the user, do not rebind; keep the
  stale `--ack` bullet with `<shared>`.
- 106–107: three empty waits → `worker-list --run <shared> --include-remote --json`, follow
  `page.nextCursor`, map rows with `state.py owner <row.dispatchId>`, act on `live` only.

- [ ] **Step 1: Edit `SKILL.md`** per the list above.
- [ ] **Step 2: Edit `orca-commands.md`** per the list above.
- [ ] **Step 3: Check no per-mission Run text is left:**
  `grep -n -E "run-create|run_id|<run_id>|across runs|nudge|reclaimable" skills/pipeline/SKILL.md skills/pipeline/references/orca-commands.md`
  Expected: only the binding block's single `run-create` and the three-empty-waits
  `worker-list`; no `<run_id>`, no `nudge`, no `across runs`.
- [ ] **Step 4: Check every "arm the wait" says "if none is running":**
  `grep -n -i "arm the wait" skills/pipeline/SKILL.md` — every hit carries it.
- [ ] **Step 5: Commit:** `git add skills/pipeline/SKILL.md skills/pipeline/references/orca-commands.md` —
  "Bind the coordinator to one saved Run and wait once for every mission".

---

### After Task 2

- Re-run `python3 -I -m unittest scripts/state_test.py -v`.
- hawkeye done-check on `git diff 47a0d12..HEAD` against the spec.

## Spec coverage

| Spec section | Task |
|---|---|
| 1 Saved Run | 1 (`run`), 2 (Places) |
| 2 Binding | 2 (step 1 subsection, orca-commands binding block) |
| 3 Mission ↔ Dispatch | 1 (`owner`, lists, `--run-id`, raw append), 2 (record rules, `payload.dispatchId`) |
| 4 One wait | 2 (Waiting rewrite, every "arm the wait") |
| 5 `consumer_fenced` | 2 (Waiting, orca-commands checks) |
| 6 Release, Finish, Abort | 2 (step 5, Finish, Abort) |
| Tests 1–11 | 1 |
| Not touched list | Global Constraints |
