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
Change: implement Task {n} of the plan exactly as written. Run `flutter analyze` on the
touched package (filter with grep 'error •', never head). Add or update the unit tests the plan
lists. Commit with message `#{TICKET} {type}({scope}): <what>`; one commit per task, no push.
If the plan has a gap you cannot close without guessing, stop and send worker_done
--outcome failed with the gap in the body.
Ownership: only the files Task {n} names.
Observable acceptance: analyzer shows no new errors, the task's tests pass, one commit exists,
worker_done --outcome succeeded --files-modified <csv>.
```

## reviewer

```
Target: worktree {worktree_path}, branch {branch}, base {base_branch}. Spec: {spec_path}.
Plan: {plan_path}.
Change: review `git diff {base_branch}...HEAD` against the spec and the plan. Look for logic
holes: wiring and ordering bugs, guard mismatches, stale state, edge cases outside the main
path, spec items not implemented, tests that do not test the decision. Run `flutter analyze`
and the plan's unit tests yourself. Write findings to {review_path} with path:line per finding.
Make no code changes.
Observable acceptance: if there is nothing the user must look at, worker_done --outcome
succeeded with body starting `APPROVED`. Otherwise worker_done --outcome failed with body
starting `NEEDS_USER: <one line>` and --report-path {review_path}; then stay idle in this
terminal so the user can read and discuss the findings here.
```
