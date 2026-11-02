# Persistent Coordinator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One long-lived coordinator session that tools and plain Claude sessions reach through
`send --to run:<shared>`, that never loses a message across a crash, restart or `/compact`,
and that a launchd watchdog restarts when its terminal is gone.

**Architecture:** File state stays in `scripts/state.py` (stdlib, no Orca calls): handled log,
scan floor, notices, notes, heartbeat, mission files. Everything that calls `orca` from the
coordinator goes through `scripts/coord.py`; every git/file/PR step on a mission goes through
`scripts/mission_ops.py`; the watchdog is `scripts/watchdog.py` (pure `decide()` + a thin
runner + a plist printer). The board gains a notices block and a coordinator health line.
`SKILL.md` and `orca-commands.md` are rewritten to call these scripts instead of raw
`git`/`rm`/`mv`/redirects, so one narrow allowlist covers the whole loop.

**Tech Stack:** Python 3 stdlib (`unittest` via subprocess, like `scripts/state_test.py`),
Claude Code plugin hook module (`hooks/register.tsx`, tests with `claude plugin test .`),
Markdown skill docs, macOS launchd.

**Spec:** `docs/superpowers/specs/2026-11-02-persistent-coordinator-design.md` (commit `7393295`).
Read it before any task; section numbers below (§N) point into it.

## Global Constraints

- State root: `~/.claude/pipeline` (`ROOT` in `state.py`). New files at the root:
  `handled.jsonl`, `scan.json`, `notices.jsonl`, `coordinator-notes.md`, `heartbeat`,
  `watchdog.json`. Mission files: `ROOT/files/<repo-slug>/<id>/`.
- `coordinator.json` keeps every field it has; `run --set` changes only `run_id`, `updated`
  (and `created` when missing). New field: `terminal`.
- Inbox scan command, exactly: `orca orchestration inbox --terminal run:<shared> --limit <n> --full --json`, default `<n>` = 100.
- Wait command, exactly: `orca orchestration check --run <shared> --wait --types "worker_done,escalation,question" --timeout-ms 900000 --full --json`.
- No `--ack` anywhere (Orca 1.4.246: a consuming check marks its batch handled).
- Heartbeat stale after 20 min. Launch lock 10 min. A launch failed when, 5 min after it, the
  heartbeat is still older than the launch. Two failed launches in a row → paused until
  `watchdog.py resume`.
- The watchdog never types into any terminal (user decision).
- Coordinator launch, exactly: `orca agent launch --agent claude --surface terminal --worktree path:<ws> --prompt "/pipeline" --json`.
- Exit codes for new `state.py` subcommands: 0 ok, 3 bad/missing file or refused, 5 scan
  window too short. Corrupt JSON in any root file → exit 3 with the path on stderr; never
  treat it as empty.
- Every script runs as `python3 -I <abs path>`; scripts that import `state.py` add their own
  folder to `sys.path` first (`-I` drops it).
- No refactor, rename or reformat outside the lines each task names. Never push.

## Review Focus

1. **Scan before the floor is seeded** → `scan pending` must refuse (exit 3), never route the
   whole inbox history. Test in Task 2: `test_pending_refuses_unseeded`.
2. **Message consumed by the wait, crash before `handled start`** → the next scan routes it
   exactly once; after `handled answer` a second scan skips it. Task 2:
   `test_pending_routes_consumed_once`.
3. **`handled.jsonl` with a corrupt line** → exit 3, not "unanswered" (that would rerun a
   push). Task 2: `test_handled_corrupt_exit3`.
4. **Orca not answering during a watchdog run** (`terminal list` fails) → `decide()` must not
   launch (it could fence a live coordinator). Task 6: `test_decide_unknown_handles_never_launches`.
5. **A command the skill runs is not on the allowlist** (one prompt stalls the session) →
   Task 7 test `test_every_skill_command_allowed` parses the code blocks of `SKILL.md` and
   `orca-commands.md` after Task 8 and checks each against the generated rules.

---

## File map

| File | Task | Responsibility |
|---|---|---|
| `scripts/state.py` | 1, 2, 3 | file state only; new subcommands `handled`, `scan`, `notice`, `note`, `heartbeat`, `file`; `run --terminal` |
| `scripts/state_test.py` | 1, 2, 3 | new test classes per subcommand |
| `scripts/coord.py` (new) | 4 | coordinator's Orca calls: `wait`, `scan`, `advance`, `seed` |
| `scripts/coord_test.py` (new) | 4 | with a fake `orca` on `PATH` |
| `scripts/mission_ops.py` (new) | 5 | mission git/file/PR steps and watchers |
| `scripts/mission_ops_test.py` (new) | 5 | temp git repos, fake `gh` |
| `scripts/watchdog.py` (new) | 6 | `decide()`, `run`, `resume`, `plist` |
| `scripts/watchdog_test.py` (new) | 6 | `decide()` table + runner with fake `orca` |
| `scripts/coordinator_setup.py` (new) | 7 | prints the workspace `.claude/settings.json` |
| `scripts/allowlist_test.py` (new) | 7 | rules cover every command in the docs |
| `hooks/register.tsx`, `hooks/board.test.ts`, `types/index.d.ts` | 9 | notices block, coordinator line |
| `skills/pipeline/SKILL.md`, `references/orca-commands.md`, `README.md` | 8 | the new loop, cutover steps |

Order: 1 → 2 → 3 → 4 → 5 → 6 → 8 → 7 → 9 → 10. Task 7's test reads the docs Task 8 writes.

---

### Task 1: `run` keeps fields and stores the terminal

**Files:** Modify `scripts/state.py:188-205` (`cmd_run`), `:253` (parser). Test: `scripts/state_test.py` class `RunTest`.

**Interfaces:** Produces `state.py run --terminal <handle>` (updates `terminal`, keeps the rest; exit 3 when the file is missing or has no `run_id`) and `run --set <id>` that keeps unknown keys.

- [ ] **Step 1: Failing tests** in `RunTest`:
  - `test_run_set_keeps_other_fields`: write `{"run_id":"run_a","created":"c","terminal":"term_1","x":1}`; `run --set run_b`; file has `run_id=="run_b"`, `terminal=="term_1"`, `x==1`, `created=="c"`.
  - `test_run_terminal_sets_field`: `run --set run_a`; `run --terminal term_9` exit 0; file `terminal=="term_9"`, `run_id=="run_a"`.
  - `test_run_terminal_without_file_exit3`: exit 3, no file created.
- [ ] **Step 2:** `python3 -I scripts/state_test.py -v RunTest` → 3 new FAIL, old PASS.
- [ ] **Step 3:** `cmd_run` merges into the loaded dict (`dict(data or {})`) before `write_json`; add `--terminal` (`dest="terminal"`), mutually usable with `--set`.
- [ ] **Step 4:** whole file passes: `python3 -I scripts/state_test.py -v`.
- [ ] **Step 5:** commit `state: run --set keeps fields, run --terminal`.

### Task 2: handled log and scan floor (§4)

**Files:** Modify `scripts/state.py` (new functions + parsers). Test: `scripts/state_test.py` classes `HandledTest`, `ScanTest`.

**Interfaces — produces (Task 4 imports these from `state`):**
- `handled_status(msg_id: str) -> str` → `"none" | "started" | "answered"`.
- `pending_rows(rows: list[dict], run_id: str, floor: int) -> list[dict]` — rows whose `to_handle == f"run:{run_id}"`, `sequence > floor`, status not `answered`; sorted by `sequence` ascending.
- `next_floor(rows: list[dict], run_id: str, floor: int) -> int` — the largest `sequence` S ≥ floor such that every matching row with `floor < sequence ≤ S` is `answered`; `floor` when none.
- `window_short(rows: list[dict], floor: int, limit: int) -> bool` — `len(rows) >= limit and min(sequence) > floor`. Sequences are global across mailboxes, so a gap alone is not "short".
- CLI: `handled start <msg> --seq N --type T [--from F] [--kind outside|mission] [--summary S]`;
  `handled answer <msg> [--summary S]` (copies `seq` from the start line; exit 3 when there is
  none); `handled get <msg>` prints the status; `handled open` prints one JSON line per
  started-not-answered entry.
  `scan seed --run R` (stdin: inbox JSON) sets floor = max `sequence` of matching rows, exit 3
  when `scan.json` exists; `scan floor` prints it, exit 3 when not seeded;
  `scan pending --run R --limit N` (stdin) prints a JSON array, exit 3 unseeded, exit 5 and a
  `window short` line on stderr when `window_short` (still prints the rows);
  `scan advance --run R` (stdin) stores `next_floor` and prunes `handled.jsonl` lines with
  `seq <= floor`.
- `handled.jsonl` line: `{"msg_id","seq","type","from","kind","status","at","summary"}`.
  `scan.json`: `{"run_id","floor","updated"}`. Stdin is the full `inbox --json` output
  (`{"ok":true,"result":{"messages":[...]}}`).

- [ ] **Step 1: Failing tests** (fixture rows use the real keys: `id`, `sequence`, `to_handle`, `type`, `payload`, `body`):
  - `test_handled_start_answer_get`: start → `get` prints `started`; answer → `answered`.
  - `test_handled_answer_without_start_exit3`.
  - `test_handled_open_lists_only_unanswered`.
  - `test_handled_corrupt_exit3` (Review Focus 3): a non-JSON line → `get` exit 3, path on stderr.
  - `test_pending_refuses_unseeded` (Review Focus 1): exit 3, stdout empty.
  - `test_seed_sets_max_then_refuses_second_seed`.
  - `test_pending_routes_consumed_once` (Review Focus 2): seed with seq 10; inbox has seq 11 (question) → pending `[11]`; `handled start/answer` 11 → pending `[]`.
  - `test_pending_ignores_other_mailboxes`: row `to_handle: "run:other"` left out.
  - `test_pending_oldest_first`: input 13, 12 → output order 12, 13.
  - `test_advance_stops_at_first_unanswered`: floor 10, rows 11 answered, 12 started, 13 answered → floor 11; `handled.jsonl` keeps 12 and 13 lines, drops 11.
  - `test_window_short_exit5`: floor 10, limit 2, rows 20, 21 → exit 5, rows still printed.
- [ ] **Step 2:** run → new tests FAIL.
- [ ] **Step 3:** implement the four functions and parsers; reads of `handled.jsonl` raise exit 3 on a bad line; writes append with one `write`. Prune rewrites through `write_json`'s temp-file pattern (text, not JSON — add `write_text(path, text)` beside `write_json`).
- [ ] **Step 4:** whole file passes.
- [ ] **Step 5:** commit `state: handled log and inbox scan floor`.

### Task 3: notices, notes, heartbeat, mission files (§5, §6, §2)

**Files:** Modify `scripts/state.py`. Test: `scripts/state_test.py` classes `NoticeTest`, `NoteTest`, `HeartbeatTest`, `FileTest`.

**Interfaces — produces:**
- `notice add --kind K --line L [--mission M]` prints the new id (`n_<epoch ms>`); `notice list [--all]` one JSON line each (open only by default); `notice clear <id>` / `notice clear --all`. Line shape `{"id","at","kind","mission","line","cleared"}`; clear appends a `{"id","cleared":true,"at"}` line (append-only; list folds them).
- `note add <text>` appends `- <iso time> <text>` to `coordinator-notes.md`; `note show` prints the file or nothing (exit 0 either way — the compact hook calls it).
- `heartbeat --terminal <h>` writes `heartbeat` as `{"at": <epoch ms>, "iso", "terminal"}` via `write_json`.
- `file write <slug> <id> <name>` (stdin → `ROOT/files/<slug>/<id>/<name>`, prints path; `name` may hold one `/` level, e.g. `readings/ui.md`; refuses `..` and absolute names with exit 3); `file dir <slug> <id>` creates and prints the folder.

- [ ] **Step 1: Failing tests:** `test_notice_add_list_clear`, `test_notice_list_all_shows_cleared`, `test_note_show_empty_exit0`, `test_note_add_then_show`, `test_heartbeat_fields`, `test_file_write_and_dir`, `test_file_write_refuses_dotdot`, `test_list_ignores_files_folder` (a `files/repo/m1/pr.json` must not appear in `state.py list` or make `owner` fail).
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** implement. `open_missions` and `cmd_list` skip the `files` folder by name.
- [ ] **Step 4:** whole file passes.
- [ ] **Step 5:** commit `state: notices, notes, heartbeat, mission files`.

### Task 4: `coord.py` — the coordinator's Orca calls (§2, §4)

**Files:** Create `scripts/coord.py`, `scripts/coord_test.py`.

**Interfaces:**
- Consumes: Task 2 functions, Task 3 `heartbeat`/`notice` (call `state.py` functions in-process).
- Produces CLI (each prints JSON or a short line; non-zero exit passes Orca's error through):
  - `coord.py wait --run R --out PATH` — writes the heartbeat (terminal from `$ORCA_TERMINAL_HANDLE`), then runs the Global Constraints wait command and writes its stdout to PATH (no shell redirect). Meant for background Bash.
  - `coord.py scan --run R [--limit 100]` — runs the inbox scan command, prints `pending_rows` as JSON; on `window_short` writes a notice (`kind=scan`) and exits 5.
  - `coord.py advance --run R [--limit 100]` — same inbox call, then `scan advance`.
  - `coord.py seed --run R` — same inbox call, then `scan seed`.
- `inbox_argv(run: str, limit: int) -> list[str]` and `wait_argv(run: str) -> list[str]` as module functions (tested directly).

- [ ] **Step 1: Failing tests.** A fake `orca` script in a temp dir first on `PATH` prints a canned inbox JSON and logs its argv.
  - `test_inbox_argv_exact`: equals `["orca","orchestration","inbox","--terminal","run:R","--limit","100","--full","--json"]` (Review Focus: `--full`, bodies > 200 chars).
  - `test_wait_argv_has_no_ack`: contains `--full`, `--wait`, `--timeout-ms`, `900000`; no `--ack`.
  - `test_wait_writes_out_and_heartbeat`.
  - `test_scan_prints_pending` and `test_scan_window_short_writes_notice_exit5`.
  - `test_orca_error_passthrough`: fake `orca` exits 1 with `{"ok":false,...}` → `coord.py scan` exits 1, floor unchanged.
- [ ] **Step 2:** `python3 -I scripts/coord_test.py -v` → FAIL.
- [ ] **Step 3:** implement with `subprocess.run(argv, capture_output=True, text=True)`.
- [ ] **Step 4:** pass.
- [ ] **Step 5:** commit `coord: wait, scan, advance, seed`.

### Task 5: `mission_ops.py` — mission-scoped git, file and PR steps (§11)

**Files:** Create `scripts/mission_ops.py`, `scripts/mission_ops_test.py`.

**Interfaces — every subcommand takes `<slug> <id>`, reads the mission with `state.load`, and touches only that mission's `repo`, worktree, branch and `files/` folder:**
- `docs-commit` — SKILL step 5: in `stages.worktree.path`, `git switch -c <branch>`; copy spec and plan (same relative path); `git add` + `git commit -m "#<TICKET> docs(<scope>): add spec and plan"` (no ticket: drop `#<TICKET> `; `<scope>` = `--scope` arg); only after that, per source file in `repo`: `git ls-files --error-unmatch` exit 1 → remove, else keep. Prints one JSON line `{"kept":[...],"removed":[...]}`.
- `prep-commit` — Plan mode P1 exactly as `SKILL.md` Plan mode P1 says (detached-HEAD and merge/rebase refusal, `add -- <spec> <plan>`, commit with paths after `--`, reset on failure). Prints the short sha.
- `move-doc --to <rel>` — Plan mode Switch move: untracked → `mv`, tracked/other → `cp` and report.
- `push` — `git -C <worktree> push -u origin <branch>`; refuses when the current branch is not the mission branch (exit 3). Never `--force`.
- `pr-split` — `pr-body.md` → `pr-title.txt` + `pr-body-rest.md` in the mission's files folder; title empty or > 70 chars → `#<TICKET> feat(<scope>): <title>`. Prints the title.
- `greptile-delay --seconds N` — sleeps N, prints `greptile delay over for <id> PR <n>`.
- `merge-watch` — the loop in `orca-commands.md` Watchers, writing `pr-final.json` into the files folder; exit 0 on MERGED/CLOSED, 2 after 6 h. `--interval` and `--deadline` flags for tests.

- [ ] **Step 1: Failing tests** in temp git repos (origin = a bare temp repo) and a fake `gh` on `PATH`:
  `test_docs_commit_removes_untracked_keeps_tracked`, `test_docs_commit_no_ticket_message`, `test_prep_commit_refuses_detached_head`, `test_prep_commit_resets_on_hook_failure` (a failing `pre-commit` hook → spec/plan unstaged, exit non-zero), `test_push_refuses_other_branch`, `test_pr_split_long_title_falls_back`, `test_merge_watch_writes_final_on_merged`, `test_merge_watch_timeout_exit2`.
- [ ] **Step 2:** `python3 -I scripts/mission_ops_test.py -v` → FAIL.
- [ ] **Step 3:** implement; all git calls are `git -C <path> …` argv lists, never a shell.
- [ ] **Step 4:** pass.
- [ ] **Step 5:** commit `mission_ops: mission-scoped git, PR and watcher steps`.

### Task 6: `watchdog.py` (§9)

**Files:** Create `scripts/watchdog.py`, `scripts/watchdog_test.py`.

**Interfaces:**
- `decide(obs: dict, now_ms: int) -> tuple[str, str]` — pure; returns `(action, reason)` with action in `ok | launch | notice | locked | paused`. `obs` keys: `saved_terminal` (str|None), `live_handles` (set|None — None means `terminal list` failed), `bound_run` (str|None, from `run-current --from <saved>`), `shared_run` (str), `screen` (str), `heartbeat_ms` (int|None), `last_launch_ms` (int|None), `failures` (int), `paused` (bool).
- Rules in order: paused → `paused`; `live_handles is None` → `notice "orca not answering"`; saved terminal missing from `live_handles` (or no saved terminal) → `locked` when `now - last_launch < 10 min`, else `launch`; `bound_run != shared_run` → `notice "fenced"`; screen contains `Do you want to proceed?` or `Do you want to create` → `notice "permission prompt"`; heartbeat missing or older than 20 min → `notice "not waiting"`; else `ok`.
- Failure count: a `run` that finds `last_launch_ms` set, `now - last_launch ≥ 5 min` and `heartbeat_ms < last_launch_ms` adds 1 to `failures` and clears `last_launch_ms`; a fresh heartbeat after a launch resets `failures` to 0; `failures ≥ 2` sets `paused` and writes a notice.
- `watchdog.py run --workspace <ws>`: `orca status --json` fails → `orca open --json` once; gathers `obs`; acts; stores `{last_launch_ms, failures, paused}` in `watchdog.json`. A `notice` is written only when its reason differs from the last one stored (no notice every minute).
- `watchdog.py resume` clears `paused` and `failures`.
- `watchdog.py plist --workspace <ws> [--python /usr/bin/python3]` prints a launchd plist: label `com.mission-pipeline.coordinator-watchdog`, `StartInterval` 60, `RunAtLoad` true, `ProgramArguments` = python, `-I`, absolute `watchdog.py`, `run`, `--workspace`, ws; `StandardErrorPath` `~/.claude/pipeline/watchdog.log`; `EnvironmentVariables.PATH` includes `/Applications/Orca.app/Contents/Resources/bin`.

- [ ] **Step 1: Failing tests:** one `decide` test per rule (incl. `test_decide_unknown_handles_never_launches`, Review Focus 4, and `test_decide_lock_blocks_relaunch`); `test_failures_pause_after_two`; `test_notice_not_repeated`; `test_run_opens_orca_when_status_fails` (fake `orca` logs argv); `test_plist_is_valid` (`plistlib.loads` and the keys above).
- [ ] **Step 2:** `python3 -I scripts/watchdog_test.py -v` → FAIL.
- [ ] **Step 3:** implement.
- [ ] **Step 4:** pass.
- [ ] **Step 5:** commit `watchdog: decide, run, resume, plist`.

### Task 8: rewrite the skill docs (§1–§12)

(Before Task 7, whose test reads these files.)

**Files:** Modify `skills/pipeline/SKILL.md`, `skills/pipeline/references/orca-commands.md`, `README.md`. `references/roles.md`: replace any `<scratchpad>` path with the `files/` folder (none found today; confirm with grep and leave it if still none).

**Interfaces:** consumes the CLIs of Tasks 1–6 by name; every command in a code block must be one the Task 7 rules allow.

- [ ] **Step 1:** `SKILL.md` edits, each tied to the spec:
  - Places table (`:44-61`): mission files → `~/.claude/pipeline/files/<repo-slug>/<id>/` written with `state.py file write`; new rows for handled log, scan floor, notices, notes, heartbeat.
  - Loop step 1 Intake: the mission's repo is required and checked with `orca repo list --json` (§7); `/pipeline` with no args = Binding + watchers + recovery + `coord.py scan` + wait + status (§1).
  - Binding (`:73-82`): every session start; saves `run --terminal $ORCA_TERMINAL_HANDLE`; first Binding of the dedicated coordinator runs `coord.py seed` once (cutover seed); reads `state.py note show` and `handled open`; re-arms watchers (§10).
  - Steps 2–9: `--worktree path:<repo>` for readers/senior/planner; `mission_ops.py` calls replace raw `git`/`cp`/`rm`/`mv`/`sed`; `orca worktree create --repo <selector> --no-parent`.
  - Waiting (`:263-318`): wait = `coord.py wait …` (background); routing = §4 table; `handled start`/`answer` around every message; after every wake `coord.py scan` then `coord.py advance`; remove `--ack`, "Unarmed gap", replay text (`:284`, `:291-294`, `:302-304`); wait always armed (§2).
  - New section **Outside asks** (§3, §4, §8): free text; same-wake reply; status reply lists missions, pending decisions with report paths, senior handles, open notices.
  - Every "tell the user" also `state.py notice add` (§6).
  - Red flags: add "This ask has no owner, I'll skip it." → outside ask; answer it. And "I'll write mission.md with the Write tool." → `state.py file write` (the Write tool prompts there, L6).
- [ ] **Step 2:** `orca-commands.md`: replace the Binding, wait, PR and Watchers blocks with the script calls; delete the `--ack` lines (`:56`) and the `consumer_fenced`-on-`--ack` paragraph (`:114-116`); add the inbox scan line.
- [ ] **Step 3:** `README.md`: new section **Persistent coordinator** — create the workspace folder (default `~/orca/pipeline-coordinator`, a git repo so `orca repo add` accepts it), `orca repo add`, write settings with `coordinator_setup.py`, first launch by hand (answer the trust dialog once), install the plist (`watchdog.py plist > ~/Library/LaunchAgents/…`, `launchctl load …`), cutover rule (no live worker; close the old session after the new Binding), and `watchdog.py resume`.
- [ ] **Step 4:** checks: `grep -n -- "--ack" skills/ -r` → no hits; `grep -n "<scratchpad>/pipeline/<id>" -r skills/` → no hits; `grep -n "Unarmed gap" skills/pipeline/SKILL.md` → no hits.
- [ ] **Step 5:** commit `skill: persistent coordinator loop`.

### Task 7: workspace settings and allowlist test (§11)

**Files:** Create `scripts/coordinator_setup.py`, `scripts/allowlist_test.py`.

**Interfaces:**
- `settings(plugin_root: str) -> dict` and CLI `coordinator_setup.py settings --plugin-root <abs>` printing it. Shape: `permissions.defaultMode = "acceptEdits"`; `permissions.allow` = `Bash(<prefix>:*)` for: each `orca` subcommand in spec §11 plus `orca orchestration inbox`, `orca repo list`; `gh pr create`, `gh pr list`, `gh pr view`; `python3 -I <root>/scripts/state.py`, `…/coord.py`, `…/mission_ops.py`; `pgrep -f`. `permissions.deny` = `Bash(orca terminal send:*)`, `Bash(orca automations:*)`, `Bash(orca agent:*)`, `Bash(gh api:*)`, `Bash(git push --force:*)`, `Bash(git push -f:*)`. `hooks.SessionStart` = one entry, matcher `compact`, command `python3 -I <root>/scripts/state.py note show`.
- `allowed(cmd: str, rules: dict) -> bool` in the test: true when some allow prefix is a prefix of `cmd` and no deny prefix is (the L6-verified prefix behaviour; `${CLAUDE_PLUGIN_ROOT}` in docs is replaced with the real root before matching).

- [ ] **Step 1: Failing tests:** `test_settings_shape` (exact deny list, defaultMode, hook command); `test_every_skill_command_allowed` (Review Focus 5: every line in fenced code blocks of `SKILL.md` and `orca-commands.md` that starts with `orca `, `gh `, `python3 `, `pgrep ` — after stripping comments and `<placeholders>` — is `allowed`); `test_no_raw_git_or_rm_in_skill` (no code line starts with `git `, `rm `, `mv `, `cp `, `sed `).
- [ ] **Step 2:** `python3 -I scripts/allowlist_test.py -v` → FAIL.
- [ ] **Step 3:** implement `settings()`; fix any doc line Task 8 left uncovered (in the doc, not by widening a rule).
- [ ] **Step 4:** pass, and all earlier test files still pass.
- [ ] **Step 5:** commit `setup: coordinator workspace settings and allowlist test`.

### Task 9: board — notices and coordinator line (§6, §9)

**Files:** Modify `hooks/register.tsx` (beside `healthLineOf`, `load`, the Pane render), `hooks/board.test.ts`, `types/index.d.ts` (add `Notice`).

**Interfaces:**
- `type Notice = { id: string; at: string; kind: string; mission?: string; line: string }` in `types/index.d.ts`.
- `export function noticesOf(text: string): Notice[]` — folds `notices.jsonl` (clear lines remove their id); skips bad lines; newest first.
- `export function coordinatorLineOf(heartbeat: string | undefined, now: number): HealthLine` — missing/unparsable → `{text: 'Coordinator · not started', tone: 'idle'}`; age < 20 min → `{text: 'Coordinator ✓ waiting · <ageOf>', tone: 'ok'}`; else `{text: 'Coordinator ✗ no wait for <ageOf>', tone: 'err'}`.
- `load()` also reads `notices.jsonl` and `heartbeat` from the root (missing files are fine). Render: up to 3 notices as `! <line>` (red) above the rows, then `+N more` dim; the coordinator line above the LSP line. Both also on the "No open missions." view.

- [ ] **Step 1: Failing tests** in `board.test.ts`: `noticesOf folds clears`, `noticesOf skips bad lines`, `coordinatorLineOf missing/fresh/stale` (19 min ok, 21 min err), and one mount test with the fake fs holding a notice (extend `fakeFs` with root files).
- [ ] **Step 2:** `claude plugin test .` → new tests FAIL.
- [ ] **Step 3:** implement.
- [ ] **Step 4:** `claude plugin test .` → all pass.
- [ ] **Step 5:** commit `board: notices and coordinator health line`.

### Task 10: done-check and live smoke (no code)

- [ ] **Step 1:** all suites: `for t in state coord mission_ops watchdog allowlist search_stats; do python3 -I scripts/${t}_test.py || exit 1; done` and `claude plugin test .`.
- [ ] **Step 2:** hawkeye reviews `git diff main...HEAD` against the spec.
- [ ] **Step 3 (needs the user's yes):** live smoke on a throwaway Run in a throwaway workspace — seed; `send` a question from a plain terminal; coordinator answers with `thread_id` match; kill the coordinator after its wait consumed a second question and before it answers → relaunch → scan answers it once; watchdog `run` once with the terminal closed → launches; once with a permission prompt on screen → notice only.
- [ ] **Step 4:** report results; cutover itself is the user's step (README section).

## Spec coverage

| Spec § | Task |
|---|---|
| §1 launch, `/pipeline` no args, handle | 1, 8 |
| §2 always-armed wait, heartbeat | 3, 4, 8 |
| §3 send channel, thread_id | 8 (docs for tools in README) |
| §4 routing, handled log, scan, floor, seed, prune | 2, 4, 8 |
| §5 notes, compact hook, mission files, no Write tool | 3, 7, 8 |
| §6 notices | 3, 9, 8 |
| §7 target repo | 8 |
| §8 decisions from tools, status reply | 8 |
| §9 watchdog, start table, launchd | 6, 8 (README) |
| §10 watchers at Binding | 5, 8 |
| §11 permissions | 5, 7 |
| §12 changes list | 1–9 |
| Cutover | 8 (README), 10 |

Open items carried from the spec, not decided here: the largest `--limit` Orca accepts
(Task 4 keeps 100 and the window-short notice); reply to a closed sender terminal (UNKNOWN,
documented in README for tool authors).
