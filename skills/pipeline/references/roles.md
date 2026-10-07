# Role task specs

Each block is the `--spec` text for one worker. Replace every `{placeholder}`. Keep the
Orca preamble rules: the worker gets its Task and Dispatch IDs injected; it must end with
`worker_done` exactly once.

Common tail, append to every spec:

```
Constraints: do only this task. Do not push. Do not run `flutter run`. Do not run widget or
integration tests. Read your coordinator follow-ups at natural checkpoints and once before
you finish. Finish with ONE `worker_done` carrying a three-sentence summary and an explicit
--outcome.
```

## reader

```
Target: {repo} on the current worktree. Angle: {angle}.
Mission text: {mission_path}.
Change: write a findings file at {readings_path} that answers, for this angle only: which
files and symbols are involved (path:line), how the current behaviour works, what the mission
would have to touch, and what you could not verify. Cite every claim as path:line or mark it
INFERRED. No code changes.
Ownership: only {readings_path}.
Observable acceptance: the file exists, every section cites file:line, and your worker_done
carries --report-path {readings_path} --outcome succeeded.
```

## senior

```
Target: {repo}, current worktree. Mission text: {mission_path}. Readings: {readings_paths}.
Change: design the solution together with the user, who will type in THIS terminal. Open
with a short summary of what the readings say and the 2 to 3 design options you see. Ask the
user one question at a time. When the user says the design is settled, write the spec to
{spec_path} (sections: Goal, Scope and non-goals, Current behaviour with citations, Design,
Data contract, UI, Edge cases, Test list, Open questions). Then ask the user to confirm the
file; only after they confirm, send worker_done.
Ownership: only {spec_path}. No code changes.
Observable acceptance: {spec_path} exists, user confirmed it in this terminal, worker_done
carries --report-path {spec_path} --outcome succeeded.
```

## planner

```
Target: {repo}, current worktree. Spec: {spec_path}.
Change: if the spec already lists ordered tasks with file paths and acceptance per task, do not
write a plan. Otherwise write a light plan to {plan_path}: file map, task boundaries, exact
interfaces between tasks, task order, Review Focus (unspecified inputs likely to break), unit
test list (no widget tests), and a spec-coverage check. Each task must name its files, what to
change, and how to verify with `flutter analyze` and unit tests. Say whether tasks touch
disjoint files (parallel-safe).
Ownership: only {plan_path}. No code changes.
Observable acceptance: worker_done --outcome succeeded --report-path <plan or spec path>, and
the FIRST line of its body is exactly:
tasks: <N>; parallel: <yes|no>; spec-is-plan: <yes|no>
```

## implementer

```
Target: worktree {worktree_path}, branch {branch}. Plan: {plan_path}. Spec: {spec_path}.
Change: implement Task {n} of the plan exactly as written. Generated *.g.dart files are
gitignored: run build_runner in a package only when analyze reports missing generated code.
Run `flutter analyze` on the touched package (filter with grep 'error •', never head). Add or
update the unit tests the plan lists. Commit with message `#{TICKET} {type}({scope}): <what>`;
one commit per task, no push. If the plan has a gap you cannot close without guessing, stop and
send worker_done --outcome failed with the gap in the body.
Ownership: only the files Task {n} names.
Observable acceptance: analyzer shows no new errors, the task's tests pass, one commit exists,
worker_done --outcome succeeded --files-modified <csv>.
```

## implementer (fix round)

Dispatched by the coordinator after a reviewer `FIX:` verdict, or after the user decides a
`NEEDS_USER:` finding. `{decisions}` is empty for a `FIX:` round.

```
Target: worktree {worktree_path}, branch {branch}. Spec: {spec_path}. Plan: {plan_path}.
Review report: {review_path}. User decisions: {decisions}.
Change: this is fix round {round} after review. Close every finding the report marks FIX or
higher than LOW, exactly as the report says; apply the user decisions where the report names
them. Leave LOW findings alone unless the report says they are one-line. Add the unit tests
the report lists. Run `flutter analyze` on the touched packages (grep 'error •', never head)
and the unit tests for the touched areas. Commit per logical fix with message
`#{TICKET} fix({scope}): <what>`; no push. If a finding cannot be closed without guessing, stop
and send worker_done --outcome failed with the gap in the body.
Ownership: files named by the review findings and their tests.
Observable acceptance: every FIX finding addressed, analyzer shows no new errors, tests pass,
commits exist, worker_done --outcome succeeded --files-modified <csv>.
```

## reviewer

The verdict word is the contract the coordinator acts on. Three verdicts, nothing else:

| First word of the body | Meaning | Coordinator does |
|---|---|---|
| `APPROVED` | no finding, or only LOW findings | opens the PR |
| `FIX:` | bugs, logic holes, missing spec items that need no decision | dispatches a fix round, then re-review |
| `NEEDS_USER:` | at least one finding needs a product or design decision | keeps this terminal open for the user |

```
Target: worktree {worktree_path}, branch {branch}, base {base_branch}. Spec: {spec_path}.
Plan: {plan_path}. Previous review reports: {previous_reports} (empty on round 1).
Change: review `git diff {base_branch}...HEAD` against the spec and the plan. Look for logic
holes: wiring and ordering bugs, guard mismatches, stale state, edge cases outside the main
path, spec items not implemented, tests that do not test the decision. On a later round, first
confirm every earlier finding is closed. Run `flutter analyze` and the plan's unit tests
yourself (generated *.g.dart files are gitignored; run build_runner in a package only when
analyze reports missing generated code). Write findings to {review_path}; each finding has
path:line and a severity: LOW (style, naming, a test that could be tighter, a doc line),
FIX (a bug, a logic hole, a spec item not implemented, a wrong guard; no decision needed), or
DECISION (the spec and the code disagree, or two readings of the spec lead to different code).
Make no code changes.
When the verdict is APPROVED, also write {pr_body_path}: line 1 is the PR title
`#{TICKET} {type}({scope}): <what>` (under 70 characters); then a blank line; then the body
with sections Summary (plain language, what a technician sees), What changed (per package),
Review (rounds, LOW items left), Testing (analyze, tests, what was not run). No links to
Claude sessions.
Observable acceptance, one of:
- no finding, or only LOW: worker_done --outcome succeeded, body starts `APPROVED`,
  --report-path {review_path}; {pr_body_path} exists.
- FIX findings and no DECISION: worker_done --outcome failed, body starts
  `FIX: <n> findings — <one line>`, --report-path {review_path}.
- any DECISION finding: worker_done --outcome failed, body starts
  `NEEDS_USER: <one line>`, --report-path {review_path}; then stay idle in this terminal so the
  user can read and discuss the findings here.
```

## greptile reviewer

Started 5 minutes after the PR opens. Read-only on GitHub.

```
Target: worktree {worktree_path}, branch {branch}, PR #{pr_number} on {owner_repo}
({pr_url}, base {base_branch}, head {head_sha}). Spec: {spec_path}. Internal review reports:
{review_paths}.
Change: read what the Greptile bot said about PR #{pr_number} and judge it against the real
code. Use read-only gh calls only: `gh pr view {pr_number} --comments`,
`gh api repos/{owner_repo}/pulls/{pr_number}/reviews`,
`gh api repos/{owner_repo}/pulls/{pr_number}/comments`,
`gh api repos/{owner_repo}/issues/{pr_number}/comments`. If Greptile has not commented yet,
`sleep 60` and re-check, up to 10 times, before concluding it has not run. Write to
{greptile_path}: (1) Greptile's rating or confidence score and its summary, quoted; (2) every
Greptile inline comment with path:line, VERIFIED against the code in this worktree (with
path:line) or REJECTED with the reason, and for each VERIFIED one a concrete fix (file,
change, test to add); (3) anything Greptile flagged that conflicts with the spec, named.
Constraints: do not push, do not post, edit or react to anything on GitHub. Make no code
changes.
Observable acceptance, one of:
- rating acceptable and no VERIFIED comment needs a code change (or Greptile never ran):
  worker_done --outcome succeeded, body starts `GREPTILE_OK: <score or none> — <one line>`,
  --report-path {greptile_path}.
- otherwise: worker_done --outcome failed, body starts
  `NEEDS_USER: <score> — <one line on what to fix>`, --report-path {greptile_path}; then stay
  idle in this terminal so the user can read and discuss the findings here.
```
