# Verification loop for the mission pipeline: design

Status: approved for the first build slice on 2026-11-19 by the author, on the owner's
delegation ("look at the final version ... and approve to build that"). Two design reviews are
folded in (section 10). The owner answered the five open decisions on 2026-11-21 (section 6).
Slice 1 (section 8) is built and merged into `main` (2026-11-21, the owner's yes). Left out of
slice 1: the plan gate's "named files exist" check and tier-raise reporting.

## 1. Intent

The pipeline checks code with the analyzer and unit tests only. No worker runs the product.
The owner wants a verification loop in the pipeline: a worker proves on the running app and
stack that a mission did what the ticket asked, before the PR opens. The loop must not become
a bad loop: it must stop, and a wrong output of one stage must not travel to the next.

## 2. Goals, non-goals, anti-goals

Goals

1. An independent verifier worker drives the real app and stack at three points: scope (bug
   missions), preflight (before the build) and verify (before the PR).
2. A bug is verified two ways: symptom-driven (the ticket's steps) and diff-driven (what the
   change touched).
3. The other places where a symptom appears are found before the design.
4. Every stage that produces content passes a scripted gate (no AI). `worktree` and `pr` are
   scripts already; their exit code is their gate.
5. Mission counters stop every cycle.
6. Workers ask a-tester for backend and web knowledge before they read code.
7. Defects in the requirement are found before the spec.
8. A code defect found outside the mission's scope is recorded and reaches the owner.

Non-goals

- Direct writes to a-tester. The first version reads only. The learning step (5.14) can later
  send proposals through a new MCP write tool; that tool is a change in a-tester.
- Committed regression scripts for each mission. A case can be promoted later; not in this work.
- A new mobile test tool. Marionette is already in both apps.
- CI changes.

Anti-goals (the design has failed if one occurs)

- A worker changes a case so that it passes.
- A fix is made for an environment failure.
- The loop runs with no limit, or a mission waits with no notice to the owner.
- The verifier receives the implementer's notes or the review report.

## 3. Current behaviour

- Stages: `read spec plan worktree build review pr` (`scripts/state.py:34`,
  `hooks/register.tsx:8`, `types/index.d.ts:4`).
- Worker rules forbid `flutter run` and integration tests
  (`skills/pipeline/references/roles.md:10-11`).
- The planner, implementer and reviewer specs name `flutter analyze`
  (`roles.md:58, 98, 143`): the specs are Flutter-only.
- Independent checks exist at three stages only: spec (the owner confirms), review (a separate
  reviewer, at most 2 fix rounds, `SKILL.md` step 7), pr (Greptile reviewer and CI). Read, plan
  and build pass on the worker's own `succeeded`.
- The coordinator never reads content; it acts on paths and outcome words (`SKILL.md:8-11`).
- Tools that exist: the Marionette binding in both apps
  (`apps/field_app_v2/lib/bootstrap.dart:68`, `apps/technicians/lib/runner.dart:180` in
  JMS.FIELD.VNEXT), the Playwright suite and run lock in `JMSNEXT/e2e/sso`, the local Docker
  stack.
- a-tester (`~/orca/projects/a-tester`): a knowledge model of backend and web behaviour with
  a read-only MCP server (`scripts/lib/index-query.ts:50-61`, 10 tools). No mobile knowledge;
  all files `status: observed`.

## 4. Approaches

| | Approach | Trade-off |
|---|---|---|
| A | A separate verifier stage after review | Independent check of real behaviour; slow; needs a device lock |
| B | The implementer verifies its own task during the build | Fast feedback; the author grades its own work; no parallel tasks on one simulator |
| C | The verifier writes committed test scripts | A growing regression suite; highest cost; flaky |

The owner worked from A. During the discussion A grew two earlier points (scope, preflight),
the two verification views, the stage gates and the a-tester lookup. B is rejected. C stays
possible later, per case.

## 5. Design

### 5.1 Stage order

Bug mission: `read → scope → spec → plan → preflight → worktree → build → review → verify → pr`.
Feature mission: the same without `scope`. A mission with tier `none` skips `preflight` and
`verify`; a skipped stage gets the new status `skipped`.

Where scope and preflight run: the mission worktree does not exist before the plan, and the
readers, senior and planner work in the owner's live checkout. Scope and preflight must not
run the app there. Before the first of them, the coordinator creates a detached **base
worktree** at the base branch's commit (`mission_ops.py base-worktree`), and records that
commit. When the mission worktree is made (from the base branch, as today), the coordinator
compares the branch's commit with the recorded one. If the branch moved, preflight runs once
more on the new commit (counter in 5.8). Finish removes the base worktree. Abort deletes
nothing, as today, and names the base worktree in what it leaves behind.

Mission kind: `state.py new` gets `--kind bug|feature` (default `feature`). The coordinator
takes it from the ticket type or the owner's words at intake. `feature` sets `scope` to
`skipped`.

### 5.2 The verifier role

One new role, used at scope, preflight and verify. It is an Orca worker like every other role.
It gets the spec cases, the diff (verify only) and the repo's verify skill. It never gets the
implementer's summary or the review report. It makes no code change, also no temporary one.

### 5.3 The verify skill (one per app, in the app's repo)

The pipeline stays generic. Each repo owns a skill `verify-<app>` with six parts:

- Surface: what the user touches (phone app, web app, API).
- Run: how the app or stack starts from the mission worktree.
- Drive: Marionette, Playwright, or the public API.
- Observe: screen state, logs, and saved data read from the server.
- Isolate: the lock to take; if it is held, report `BLOCKED`.
- Check: the repo's own check commands (analyzer, unit tests) that the build gate runs.

Its frontmatter also lists `shared:` (path prefixes of shared packages) and `watch:` (5.16).

First skills: `verify-field-app-v2`, `verify-technicians`. Skills for JMSNEXT
(`verify-jms-web`, `verify-jms-api`) follow the same shape: JMSNEXT missions are in scope
(owner's decision, 2026-11-21).

### 5.4 Cases

- The senior writes the verification cases in the spec, each with a stable id (`VC-01`):
  steps, the surface of each step, the expected result, the evidence to keep. These are the symptom cases (bug) or spec cases
  (feature). They are frozen: no worker edits or removes one. The spec gate stores a hash of
  the cases block in the state file; every later gate compares it. A case that looks wrong is
  a decision for the owner (`NEEDS_USER:`). After `SPEC_GAP:` the senior and the owner change
  the cases and the spec gate stores a new hash.
- A cross-surface case is one case with ordered steps: set up (API or web), act (phone app),
  assert (server or web). One verifier runs all steps. Setup goes through the public API
  unless the web screen itself is under test.
- Required case families: each mission has one or more cases for the error path (network
  failure, 401, timeout) and for permissions, or one line in the spec that says why a family
  does not apply.
- The planner maps each case to a task and sets the tier:
  `none | api | web | mobile | cross | cross-app`. `cross-app`: the diff touches a shared
  package (a path under a `shared:` prefix of the verify skill), and the cases run in both
  apps (technicians and field_app_v2). The build gate reports `tier-raise cross-app` when it
  sees such a file in the diff; the coordinator sets the tier. A gate never changes state. Android is not run:
  one iOS simulator is the known limit.
  The reviewer may raise the tier, never lower it (author's call 11). After any raise
  (from `none`, to `cross-app`, or to another surface) preflight runs on the base worktree for
  the added surface or app before verify, so verify always has a baseline. One raise per
  mission; a second waits for the owner.
- At verify, the verifier adds diff cases: one per entry point that reaches each changed
  behaviour. It also probes sibling code the diff did not touch and reports each as a finding.

### 5.5 Scope (bug missions)

1. Reproduce the symptom at the ticket's place on the base branch.
2. Take the faulty code from the readings (one reader has the angle "cause").
3. Fan out: every entry point of the faulty code, sibling code with the same pattern, every
   consumer of the same data.
4. Probe each candidate live.
5. Write the symptom map: one row per place, `reproduced | not reproduced | could not check`,
   with evidence. The senior designs from the map. A place out of scope gets a follow-up
   ticket by the owner's decision.

Verdicts: `SCOPED: <n> places`, `NOT_REPRODUCED:` (the symptom does not appear at the
ticket's place; waits for the owner), `BLOCKED:`.

### 5.6 Preflight

Runs the cases on the current code before the build:

1. Environment: stack up, accounts exist, the app points at the right tenant, fixtures can be
   created and restored.
2. Assumptions: the routes, response shapes, rights and flags the spec relies on exist.
3. Each case can be driven and observed.
4. Each new-behaviour case fails now; each regression case passes now.

Verdicts: `READY` (build starts; the baseline is kept, with the base commit), `SPEC_GAP:`
(back to the senior and the owner; the planner then runs again), `NEEDS_USER:` (a case looks
wrong), `BLOCKED:` (environment; waits for the owner).

### 5.7 Verify

Order of one run: take the device lock (5.13) → check the environment → set up fixtures →
run the frozen cases → read the diff and add diff cases → sibling probes → on a failed case,
run it once more from a clean state (a pass on the retry is recorded as flaky) → teardown,
restore, confirm by read-back → verdict. Teardown always runs.

Attribution comes from the baseline, not from a revert: a case that failed on the base
worktree at preflight and passes on the mission commit is attributed to the mission's diff.

Verdicts:

- `VERIFIED`: every case passes with evidence on the final commit. The verifier writes a
  "Verification" section for the PR body.
- `FIX:` one or more cases failed in this run, also on the in-run retry. A fix-round
  implementer reads the verify report and names the root cause; the reviewer reads the fix;
  the verifier runs all cases again.
- `NEEDS_USER:` a frozen case looks wrong, or a case passes now but never failed on the base
  (the symptom was never shown; owner's decision, 2026-11-21). When the owner agrees that a case is wrong,
  the mission returns to spec; this uses the "returns to spec" counter.
- An open `in scope` row of the found-defects list (5.12) makes the verdict `FIX:`.
- `BLOCKED:` the environment prevents the run. Never `FIX:`.

Outcome words: `VERIFIED`, `READY` and `SCOPED` are sent with `--outcome succeeded`; every
other verdict with `--outcome failed`, as the reviewer does today. The coordinator sets the
stage status from the verdict word: `FIX:` keeps the stage `active`; `NEEDS_USER:`,
`BLOCKED:`, `SPEC_GAP:` and `NOT_REPRODUCED:` set `waiting_user`. No verdict sets `failed`,
because the board shows a `failed` stage as blocked.

PR text: the reviewer writes `pr-body.md` before verify runs. The verifier writes
`verification.md`; `mission_ops.py pr-split` appends it. The coordinator reads neither.

### 5.8 Stop conditions and counters

The state file holds these counters per mission. Over a limit, the mission moves to
`waiting_user` with a notice.

| Counter | Limit |
|---|---|
| Fix rounds started by a review `FIX:` (as today) | 2 |
| Fix rounds started by a verify `FIX:`; a `FIX:` from the re-review inside such a round uses the next one | 2 |
| Returns to spec (from preflight `SPEC_GAP:` or a wrong case at verify) | 1 |
| Preflight runs again (the base branch moved, or a tier raise) | 1 each |
| Gate retries per stage, counted again for each fix round | 1 |
| The same failure in two verify runs in a row: same case id and same failure class, after a fix round | stop at once |
| A case that passed before fails after a fix | stop at once |
| Workers started per mission | a budget, value open |
| Verify run time | a budget, value open; over it is `BLOCKED:` with the cases not run |

### 5.9 Stage gates

After each stage the coordinator runs one script, `mission_ops.py gate <stage>`. It has no AI.
It prints one line only: `pass`, or `fail <n> <path>`. On a failure it writes the error list
to `<files>/gate-<stage>.md`; each error starts with a stable code (`READ-CITE-MISSING`).
Most workers are released at `worker_done`, so the coordinator starts one new Dispatch of the
same role with that path; a second failure is `waiting_user`. The coordinator reads the one
line, never the file. A gate that runs long commands (build) runs as a background Bash
call, like the wait, because a foreground call is killed at 10 minutes.

| Stage | The gate checks |
|---|---|
| read | every citation has a repo key and its `path:line` exists at that repo's HEAD; a "could not verify" section is present; the requirement findings file exists |
| scope | every map row has a status and an evidence file that exists |
| spec | required sections present; every case has steps, a surface on each step and an expected result; every requirement finding id has a resolution line; the two required case families are present or have a reason |
| plan | the plan holds a machine-readable block `case id → task number` that covers every case id of the spec (also in an HTML plan and when the spec is the plan); every named file exists or is marked new; the tier is set |
| preflight | one baseline row per case; a verdict word |
| build | each commit carries a `Task: <n>` trailer; the files of a task's commits are within that task's files; the gate runs the Check commands of the verify skill itself |
| review | a verdict word; every finding has `path:line` |
| verify | one row per case id with a result and a failure class; evidence files exist; the commit equals HEAD; the cases hash is unchanged; no `in scope` row of the found-defects list is open |

A gate proves the output is complete and consistent, not that it is correct.

### 5.10 a-tester lookup

Workers reach a-tester through its MCP server only. They do not open its files, run its `qa`
commands, or write to it.

| Stage | MCP tools |
|---|---|
| read | `search`, `trace_ticket`, `get_node` |
| scope | `chain`, `neighbours`, `trace_code` |
| spec, preflight | `why`, `governed_by`, `get_node` on access nodes |
| verify | `trace_code` per changed file, `gaps` |

Lookup rule: the node exists and its cited code did not change since the read commit → use
the node and its citations. The node is stale → read only the cited files that changed. No
node (mobile, auth, a new area) → read the code as today. A node is a cited hint, not truth.

Facts from the review of a-tester's code: `get_node` returns the node's read commit. Every
read commit is for the backend and web repo; the index holds no evidence for the mobile repo,
so `trace_code` on a mobile diff returns nothing. 10 nodes hold a dummy commit and 21 list
dirty paths: a worker treats those as stale. The server rebuilds its index at start and
refuses to start on a validation error: when the server is not available, the worker reads
the code and says so in its report.

### 5.11 Requirement check (inside the read stage)

One reader has the angle "requirement". It runs for every mission, before the senior starts.

1. Split the ticket into single statements, each with an id (`RQ-01`).
2. Check each statement against a-tester (`why`, `governed_by`, `gaps`, `trace_ticket`), and
   against the code where a-tester has no node.
3. Write `<files>/requirement-findings.md`. Each finding has an id, the statement, a type and
   a citation. Types: `ambiguous` (two readings lead to different code), `contradicts` (a
   decision, existing behaviour or another ticket says otherwise), `not testable` (no
   observable result), `missing case` (a role, state or surface is not covered),
   `already true`, `blocked by` (it needs something that is not built).
4. The senior opens with this list; the owner settles each finding in the senior's terminal.
5. The spec gate fails while a finding id has no resolution line in the spec.

For a bug mission, the scope result (reproduced or not, the other places) is added to the
same list. Findings are not sent to the ticket system; that is an outward action for the
owner.

### 5.12 Found-defects list

A code defect outside the mission's change has no owner today. Every worker appends to one
file, `<files>/found-defects.md`, through a new locked command `state.py file append` (today's
`file write` replaces the whole file, so two parallel workers would lose rows). A row has an
id, the place (`path:line` or screen), the evidence, who found it, `in scope` or
`out of scope`, and `open` or `closed`. The senior and the
owner set the scope of the rows known at spec time; a later row is `out of scope` unless the
owner says otherwise.

- `in scope` rows must be closed before `VERIFIED`. An open one makes the verify verdict
  `FIX:`, so it goes to a fix round like a failed case; the verifier closes the row when its
  probe passes.
- `out of scope` rows go to the owner as one list when the mission reaches `ready`, with a
  notice. A ticket is created only on the owner's yes.

Where code defects are looked for: build (analyzer and unit tests, run again by the gate),
review (the diff against the spec and plan), verify (frozen cases, diff cases, sibling
probes), scope and read (defects that were there before), pr (Greptile and CI).

### 5.13 Locks

The pipeline gets its own device lock in `mission_ops.py`: a lease file with the holder's
Dispatch id and an expiry, taken fail-fast (held → `BLOCKED:`), released by the verifier at
teardown and by Finish and Abort. A lease of a dead Dispatch expires.

The e2e run lock of `JMSNEXT/e2e/sso` (`scripts/run.locked.ts`) is the folder
`e2e/sso/.run.lock/` with `owner.json` `{pid, label, startedAt}`, made with an atomic
`mkdir`. A lock whose owner pid is dead is stale and is taken over. It has no queue: a waiting
run checks every 5 s and gives up after 60 minutes with exit 3.

The pipeline holds this lock through a **holder process** (owner's decision, 2026-11-21; no
change in JMSNEXT):

- `mission_ops.py` starts a small holder process. It makes the folder, writes `owner.json`
  with its own pid and the label `pipeline <mission id>`, and stays alive. Its pid goes into
  the state file, so Finish and Abort can stop it.
- Fail-fast: the folder exists and its owner pid is alive → the verifier reports `BLOCKED:`.
  A stale lock (dead pid) is cleared first, as `run.locked.ts` does.
- The holder removes the folder only while `owner.json` still names its own pid. The verifier
  stops it at teardown; Finish and Abort stop it too.
- While the pipeline holds the lock, the verifier runs Playwright with `bunx playwright test`
  directly, never through `run.locked.ts`, which would wait for the pipeline's own lock.
- Other runs wait as they do today: up to 60 minutes, then exit 3.

Not tried (INFERRED): the holder must outlive a worker that ends early, or the lock turns stale
while a run is still on the stack. The Marionette scripts that share the lock exist only on the
EDGE branch; not read.

### 5.14 Learning step (in Finish, after the merge)

Neither a fix round nor a found-defects list makes the next mission better. This step does.
It runs after the merge, because before it the code can still change.

Inputs: the verify reports (failed cases with their class), the review findings, the
found-defects list, the gate error files, and the counters that reached a limit.

1. **Pattern log.** A script appends one row per failure to `~/.claude/pipeline/patterns.jsonl`:
   mission, stage, failure class, a pattern key, and `escaped: no`. The key is the gate error
   code, or `verify:<failure class>` for a failed case. Review findings get a key only after
   the reviewer spec adds a rule tag to each finding (not in slice 1). No AI.
2. **Repeat notice.** When one pattern key is in two or more missions, the script adds a
   notice for the owner: the key and the missions. The owner decides if it becomes a line in
   the repo's code rules, a lint rule, or a new gate check. Nothing is changed automatically.
3. **Knowledge proposals.** A worker writes `<files>/knowledge-proposals.md` from the merged
   diff and the verify evidence: statements with citations for the behaviours the mission
   changed, new behaviours with no node (this is how mobile knowledge starts), and
   differences between intent and the app.
4. **Send to a-tester (first version; owner's decision, 2026-11-21).** The worker sends the
   statements of step 3 through the a-tester MCP tool `propose` (it exists since a-tester
   commit 25ef66c). One call saves one candidate file under a-tester's `candidates/`,
   uncommitted, in the a-tester main checkout; a person confirms it later (a-tester's next
   phase). The worker sets `ticket`, `by: pipeline <mission id>` and `readAt` with the
   merge commit.
   - The tool refuses a statement with no evidence bracket, and a repo bracket with no commit
     (`@commit` or `readAt`).
   - The tool does not enforce these rules, so the worker keeps to them: every statement has a
     citation; at most 15 new statements per ticket; only nodes the ticket touched; developer
     side only (the `Implemented`, `when`, `before`, `after`, `Attributes` and `does`
     sections; never `Intended` or `Why`; no verdict, no promotion).
   - `about: new` needs an area that already exists (item-catalogue, job-items, job-tasks,
     service-plans, sor). A mobile-only behaviour with no area (for example auth) cannot be
     sent; it stays in step 3's file.
   - INFERRED: the tool's `field` repo key is the mobile repo.
   - A refused call is listed in the learning report; it never fails Finish.

### 5.15 Verifier calibration

Known risk: a model used as a tester lists the problems and then approves anyway, or tests
too little. Five measures:

1. **The verdict is computed, not judged.** The verify gate derives the verdict from the case
   rows: one failed row means not `VERIFIED`. The verifier's own verdict word must equal it,
   or the gate fails.
2. **Evidence per claim.** A passed row needs evidence of the right kind: screen state for a
   function, a screenshot for layout, a server read for saved data, a second account for a
   permission. The gate checks the kind is present.
3. **The baseline is a built-in test of the verifier.** At preflight the new cases must fail
   on the base. A verifier that passes them there is wrong, or the case is; both stop the
   mission (`SPEC_GAP:`).
4. **Owner sampling.** The owner replays the evidence of the first 5 `VERIFIED` missions, then
   1 in 5. A disagreement is a row in the pattern log with the key `verifier-miss`, and the
   verifier spec is corrected.
5. **Escaped defects.** The owner records one with `mission_ops.py patterns escaped <mission>
   --ticket <bug ticket>`; the script adds a row with `escaped: yes`. Nothing links a bug
   ticket to a mission automatically. The count of escaped defects per verified mission is the measure of the
   verifier.

### 5.16 Upkeep of the verify skills

A verify skill that is out of date breaks the loop first.

1. **Self-check at every run.** The environment check of preflight and verify runs the
   skill's Run and Isolate steps first. A failure there is `BLOCKED:` with the class
   `skill-stale`, and a notice.
2. **Watch list.** The skill's frontmatter names the files it depends on (launch scripts, env
   files, bootstrap code, flavors) and the commit it was last proven at. When a mission's
   diff touches a watched file, the build gate adds a notice: "verify skill may be stale".
3. **Corrections are proposals.** The verifier writes a "Skill corrections" section in its
   report when a step did not work as written. The skill is a file in the app's repo, so a
   correction is applied through a mission or by the owner, never by the verifier.

### 5.17 File formats (author's call 12)

- **Citation** in a readings file: `[<repo key>:<path>:<line>]` or `[<repo key>:<path>:<from>-<to>]`.
  The repo keys and their paths are passed to the gate as data.
- **Could-not-verify section:** a heading line `## Could not verify`.
- **Requirement findings:** one line per finding,
  `- RQ-<nn> | <type> | <statement> | <citation or none>`.
- **Resolution line** in the spec: `- RQ-<nn>: <resolution>` under `## Requirement findings`.
- **Cases block** in the spec: from the line `<!-- cases:start -->` to `<!-- cases:end -->`.
  Inside it each case starts with `### VC-<nn> <title>`, then `family: <main|error|permission|regression>`,
  then step lines `- [<surface>] <step>` (surface: `api|web|mobile`), then `expected: <text>`.
  The hash is SHA-256 of the block's text.
- **No-case reason:** `- no error case: <reason>` or `- no permission case: <reason>` inside the block.
- **Case-to-task block** in the plan (markdown or HTML): from `<!-- case-tasks:start -->` to
  `<!-- case-tasks:end -->`, one line per case `VC-<nn>: T<n>[, T<n>]`. Then `tier: <value>`.
- **Verify report rows:** a JSON file `verify.json` beside the report:
  `{"commit": "<sha>", "cases_hash": "<hex>", "verdict": "<word>", "rows": [{"case": "VC-01",
  "result": "pass|fail|flaky|not-run", "class": "", "baseline": "fail|pass|none",
  "evidence": [{"kind": "screen|screenshot|server|second-account|log", "path": "..."}]}]}`.
  `flaky` counts as a pass and is listed in the PR text. `not-run` is not a pass.
- **Found-defects row:** `- FD-<nn> | <place> | <in scope|out of scope> | <open|closed> | <who> | <evidence>`.

### 5.18 Usage-limit safety net

The work runs on a subscription with a 5-hour usage window.

1. **Built in.** Claude Code waits in the open session and continues the task on its own
   after the limit resets; this is on by default in interactive sessions signed in with a
   subscription (v2.1.234 or later; docs: interactive mode, "Wait for a usage limit to
   reset"). Reported by the docs guide and not re-checked by the author: it stops after 3
   automatic continuations, it is not offered in background sessions, and leaving Claude
   Code cancels the wait. So every worker and the coordinator must stay open, in an
   interactive terminal.
2. **A subagent that hits the limit** is marked failed with its last output; it can be
   continued with a message (same source, not re-checked).
3. **Small units.** One commit per task and one state write per step, so a cut loses one
   task at most. Recovery (`worker-list`) finds a worker that was started before a cut.
4. **Reading the meter.** The status line input has the used share and the reset time of the
   5-hour window (same source, not re-checked). A status line script can write them to a
   file; the coordinator can then hold a `worker-start` when the share is high. Not designed
   in detail; not in slice 1.
5. **Pacing.** The worker budget of 5.8 is the guard against a mission that burns a window.

### 5.19 Parallel build safety (proposal)

Status: the owner asked on 2026-11-20 to add this as a proposal. Not in slice 1; its slice
needs the owner. Source of the idea: the Google Cloud article "5 agent orchestration patterns
backed by research" (2026-11-19), pattern 2 "Split work into lanes". It cites a study where two
agents on overlapping code succeeded about 30% less often than one agent; the author did not
read that study.

Today the planner states `parallel: yes|no` on its own word (`roles.md` lines 58–59 and 63).
With `parallel: yes` the coordinator starts one implementer per task in one wave, all in the
same mission worktree (`SKILL.md` lines 157–159). The coordinator reads only the body line,
never the plan. Two gaps follow.

1. **No one checks the overlap.** If the planner misses a shared file, two implementers edit
   it at the same time.
   - The plan holds a machine-readable **task-files block** (markdown or HTML): from
     `<!-- task-files:start -->` to `<!-- task-files:end -->`, one line per task
     `T<n>: <path>[, <path>]`, repo-relative, `(new)` after a file that does not exist yet.
     A task lists every file it changes, also files changed as a side effect: `.arb` files,
     barrel exports, `pubspec.yaml`, `pubspec.lock`.
   - The plan gate (5.9) reads the block. A path in two tasks while the planner said
     `parallel: yes` gives the pass line `pass serial`. The gate changes no state; the
     coordinator sets `stages.plan.parallel=no`, as it does for `tier-raise` (5.4).
   - The same block is the task file list that the plan gate ("every named file exists or is
     marked new") and the build gate ("the files of a task's commits are within that task's
     files") already need; 5.17 gets the format.
   - The wave stays all or nothing: one overlap makes the whole build serial. Partial waves
     (T1 and T2 together, then T3) are not proposed.
2. **Parallel implementers share one git checkout.** Separate files do not give separate
   checkouts. Risks (INFERRED from how git and Flutter work, not seen in a run): two commits at
   the same time fail on `.git/index.lock`; an implementer that runs `git commit -a` or
   `git add -A` commits another implementer's files; two `build_runner` runs in one package
   write the same generated files.
   - The implementer spec (`roles.md`, both implementer roles) adds: stage files by path only
     (`git add <the files of Task n>`); never `git add -A`, `git add .` or `git commit -a`.
     A commit that fails because `.git/index.lock` exists is tried again after a few seconds,
     at most 3 times, then the worker reports `failed`.
   - The planner spec adds: two tasks that need `build_runner` in the same package are not
     parallel-safe.
   - One worktree per implementer is not proposed: it costs a merge step for each wave.

## 6. Decisions the owner made

- Verification covers the running app and stack, not only code.
- Cross-surface cases (web setup, mobile action) must be supported.
- Bug verification is symptom-driven and diff-driven.
- Other places with the same symptom must be found and must shape the solution.
- a-tester is used through its MCP only. Its one write is `propose`, in the learning step
  (2026-11-21).
- Scripted gates after every stage, and mission counters.
- A safety net for the 5-hour usage window with automatic resume (2026-11-19).
- A requirement check, a found-defects list, required case families, and the shared-package
  rule (all four on 2026-11-19).
- A learning step, verifier calibration and upkeep of the verify skills (2026-11-19). The
  owner said the proposed MCP write function could be useful for the learning step.
- The five open decisions (2026-11-21):
  1. Standing permission: the mission request lets the verifier start the app (`flutter run`)
     and restart an API container, for the mission's own base and mission worktrees only.
  2. A bug that never appeared, and whose cases pass after the build, is `NEEDS_USER:`, not
     `VERIFIED`.
  3. The e2e run lock is held through a holder process (5.13); no change in JMSNEXT.
  4. JMSNEXT missions are in scope.
  5. `propose` is part of the first version of the learning step (5.14).

## 7. Open decisions and calls the author made (please check)

Open decisions: none. The owner answered all five on 2026-11-21 (section 6). Slice 1 still
keeps each answer as one constant or flag, so a later change is small.

Calls the author made:


1. The design is repo-neutral through the verify skill; the first skills are for the mobile
   repo. JMSNEXT missions are in scope (section 6).
2. (Moved to open decision 1.)
3. Staleness of an a-tester node: the worker compares the read commit from `get_node` with
   the code repo by git. Confirmed in a-tester's code by the review; not run on the live server.
4. A mobile mission that needs an unmerged backend change: the spec names the backend branch;
   the verifier records the backend commit; a mismatch is `BLOCKED:`.
5. After `SPEC_GAP:` the planner runs again automatically.
6. The limits in 5.8 and one retry of a failed case.
7. Failure classes from a-tester (`bug-app`, `test-drift`, `data`, `flaky`, `not-shipped`) are
   recorded on each failed case in the verify report.
8. A separate base worktree for scope and preflight (5.1).
9. No revert check; attribution comes from the preflight baseline (5.7).
10. A `Task: <n>` commit trailer and a case-to-task block in the plan (5.9).
11. The reviewer may raise the tier; one raise per mission (5.4).
12. The file formats of 5.17.
13. New stages start as `skipped` in `state.py new` until the coordinator skill drives them,
    so a mission of today's flow never shows them as pending.

Proposals the owner asked to add (not yet in a slice):

- Parallel build safety (5.19): a task-files block checked by the plan gate, and path-only
  staging for implementers that share the mission worktree.

## 8. Build slices

**Slice 1 (approved, built first; scripts and state only, the coordinator skill and the
worker specs do not change):**

- `state.py`: stages `scope`, `preflight`, `verify`; status `skipped`; `new --kind`; a
  `counters` map; `cases_hash`; `tier`; `file append` with a lock.
- `mission_ops.py`: `gate <stage>` for read, spec, plan and verify (the checks that need only
  files: formats of 5.17, citations, the cases hash, the computed verdict); `freeze-cases`;
  `patterns add | repeat | escaped`.
- Board and types: the new stage names, a short word for `preflight`, the `skipped` status.
- Unit tests for each.

Later slices (each needs the owner): the coordinator loop and worker specs (`SKILL.md`,
`roles.md`: verifier, requirement reader, gate retries, the lookup rule, the repo's own check
commands in place of Flutter-only ones); the base worktree, the device lock and the e2e lock holder (5.13); the build and
review gates; `pr-split` appending `verification.md`; the two first verify skills; the
learning step's worker; the usage meter file; how each Orca worker gets the a-tester MCP
server in its config.

## 9. What was read and what was not

Read: `SKILL.md`, `roles.md`, `README.md` of this repo; the mobile CI workflow and hooks; the
JMSNEXT `e2e/sso/README.md` and local Docker skill; a-tester's two skills, its MCP spec, one
behaviour file, one access file, the MCP tool list. Also read before slice 1: `state.py` and `mission_ops.py` in full, the head of both test
files, the stage code of `hooks/register.tsx`, `types/index.d.ts`. Not read: `coord.py`,
`watchdog.py`, `orca-commands.md`, a-tester's main design body. Not run: the
a-tester MCP server.

## 10. Design review (2026-11-19)

A reviewer read this doc against the pipeline code, a-tester's query code and the JMSNEXT run
lock script. Its findings are folded into the sections above: the checkout for scope and
preflight (5.1), the clash between `FIX:` and "same failure twice" (5.7, 5.8), the run lock
(5.13), gate retries after a worker is released (5.9), gates that needed stable ids (5.4,
5.9), missing verdicts and the outcome map (5.5 to 5.7), the fix-round counters (5.8), the
revert step (5.7), the a-tester limits (5.10), and the PR text (5.7). The reviewer did not
check `coord.py`, the full `register.tsx`, the EDGE Marionette scripts or the live MCP server.

A second review (2026-11-19, after 5.11 to 5.16 were added) found: the found-defects file
could lose rows and had no open/closed field (5.12), no rule for a tier raise after preflight
(5.4), formats a builder would have to guess (5.17), no source for some pattern keys (5.14),
no link from a bug ticket to a mission (5.15), a base that can move (5.1), and small
contradictions. All are folded in above. That reviewer did not read `coord.py`, `watchdog.py`
or the rest of `SKILL.md`. The text added after the second review (5.17, 5.18, section 8) was
not reviewed again.

Slice 1 was built on the branch `feature/verification-loop-slice-1` (worktree
`~/orca/workspaces/mission_pipeline-verify-loop`), not pushed. A done-check of its diff found
3 major and 5 minor problems; 7 are fixed on the branch with tests: a gate that breaks exits 3
with one line, evidence must be a file inside the mission's files folder, the plan and verify
gates fail with zero or unfrozen cases, `BLOCKED` is refused when a row failed, a bracket that
starts like a citation must be one, a folder is not a file, a bad case heading is an error.
Left as is: `count` and the repeat notice have no lock, because the coordinator is the one
writer. The fixes were not reviewed again.

