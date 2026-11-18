# Verification loop, slice 1: state, gates, pattern log (light plan)

Design: `docs/superpowers/specs/2026-11-19-verification-loop-design.md` (in the main checkout,
not committed), sections 5.8, 5.9, 5.12, 5.14, 5.15.1, 5.17 and 8.
Implemented inline by the session that wrote the design. Branch
`feature/verification-loop-slice-1`. No push.

Rule of the slice: scripts and state only. `skills/pipeline/SKILL.md` and
`references/roles.md` do not change, so the live coordinator behaves as before.

## File map

| File | Change |
|---|---|
| `scripts/state.py` | T1: stages, `new --kind`, new mission fields, `file append`, `count` |
| `scripts/state_test.py` | T1 tests |
| `scripts/gates.py` (new) | T2: pure checks, one function per stage |
| `scripts/gates_test.py` (new) | T2 tests on the pure functions |
| `scripts/mission_ops.py` | T2: `gate`, `freeze-cases`; T3: `patterns-add`, `patterns-repeat`, `patterns-escaped` |
| `scripts/mission_ops_test.py` | T2, T3 CLI tests |
| `hooks/register.tsx`, `types/index.d.ts`, `hooks/board.test.ts` | T4: stage names, `skipped`, the word for `preflight` |

## Interfaces

T1, `state.py`:

- `STAGES = read scope spec plan preflight worktree build review verify pr`.
- `new ... [--kind bug|feature]` (default `feature`). New top-level fields: `kind`, `tier`
  (`none`), `cases_hash` (`""`), `counters` (`{}`). New stage entries `scope`, `preflight`,
  `verify` start as `skipped` (the coordinator skill does not drive them yet).
- `file append <slug> <id> <name>`: stdin is appended under an exclusive lock; a missing
  final newline is added. Same name rules as `file write`.
- `count <slug> <id> <name>`: `counters[name] += 1`; prints `<value> <limit|->`; exit 5 when
  the value is over the limit. `LIMITS`: `fix_review 2`, `fix_verify 2`, `spec_returns 1`,
  `preflight_reruns 1`, `tier_raises 1`, `gate 1`. A name `gate:<stage>:<round>` uses the
  limit of its first part.

T2, `gates.py` (no I/O beyond reading the named files and `git`):

- `Err = (code, message)`; every function returns `list[Err]`.
- `parse_cases(text) -> (block_text | None, cases, reasons)`; `cases_hash(block_text)`.
- `gate_read(paths, repos, findings_path)`, `gate_spec(spec_path, findings_path)`,
  `gate_plan(plan_path, spec_path, frozen_hash)`,
  `gate_verify(report_path, spec_path, frozen_hash, worktree, defects_path, files_dir)`.
- `computed_verdict(rows, cases, defects) -> str`; `NEVER_SHOWN_VERDICT = "NEEDS_USER"`
  (open decision 2 as one constant).

T2, `mission_ops.py`:

- `gate <slug> <id> <stage> [--repo key=path ...]`: prints exactly one line, `pass` (exit 0)
  or `fail <n> <path>` (exit 1), writes `<files>/gate-<stage>.md`, and appends one pattern row
  per distinct error code. Unknown stage: exit 3.
- `freeze-cases <slug> <id>`: writes `cases_hash` from the spec's cases block; prints it.

T3, `mission_ops.py`, file `ROOT/patterns.jsonl`:

- `patterns-add <slug> <id> --stage S --key K [--class C]`.
- `patterns-escaped <slug> <id> --ticket T`.
- `patterns-repeat [--min 2] [--notice]` (no mission): prints one JSON line per key that is in
  `min` or more missions; `--notice` adds one notice per key, once (`ROOT/patterns-noticed.json`).

## Task order

T1 → T2 → T3 → T4. One commit per task.

## Review focus

- Old mission files have none of the new keys: every read uses `.get`.
- `file append` from 8 processes at once loses no row.
- A gate never writes mission state; only `freeze-cases` and `count` do.
- `gate` prints one line only, also on an internal error (exit 3, one line on stderr).
- Citations: a line range past the end of the file; a path with a colon; a repo key that is
  not passed; a file that exists on disk but not at HEAD.
- Cases block: a case with no steps; a step with no surface; two cases with one id; the
  no-case reason lines.
- Verify: a `not-run` row; a pass row with no evidence; a diff case id (`DC-<nn>`) that the
  spec does not hold; a report that says `VERIFIED` when a row failed.

## Not in this slice

The build and review gates (they need the `Task:` trailer and the reviewer's format), the
"named files exist" check of the plan gate (the plan has no file format yet), tier-raise
reporting, everything in the coordinator skill and worker specs.

## Tests

`python3 -I scripts/state_test.py`, `gates_test.py`, `mission_ops_test.py`; `claude plugin test .`
for the board.
