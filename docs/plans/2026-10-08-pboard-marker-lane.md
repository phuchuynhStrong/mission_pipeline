# /pboard marker lane (design S) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the stage track rows of `/pboard` with one line per mission: a status glyph, the ticket, the current stage word, the note, and a hotkey or age at the right edge, plus a legend line.

**Architecture:** Same module, same data flow. `rowsOf()` stays the one pure entry; it drops `track`, gains `stage` (the display word) and `marker` (glyph + tone). The render becomes one `Box` row per mission with fixed-width lanes and a `flexGrow` note. The `ui.focus` hook, `focusedId`, the row background and the expanded note go away: there is no focused row state.

**Tech Stack:** Claude Code plugin hook module (`hooks/register.tsx`, JSX over the pane `Box`/`Text`/`Button` from `$.ui.resolve(e)`), tests with `claude plugin test .` (file `hooks/board.test.ts`, `claude-code/testing`).

**Spec:** Paper file "pboard — panel redesign", artboards `S · marker lane` and `S · empty`
(https://app.paper.design/file/01M4CW7GBGA492VHCYMSDE4B5P/p-1-0). Chosen 2026-10-08.

**Branch:** `pboard-marker-lane` (from `main`). One commit per task. Never push.

## Global Constraints

- Pane body is 40 columns; every row fits in one line at that width. No horizontal overflow.
- Order: blocked, asking, running (stable inside a group). `TONE_RANK` unchanged.
- Hotkeys `1..9` on rows with a terminal, in display order. Unchanged.
- No "N need you" summary line. No spinner timer. The 3 s poll is the only redraw.
- Legend line is always drawn. Key hints are drawn only while `e.props.isFocused`.
- Merge glyph is `✓`. The Paper mock shows `+` only because its font lacks `✓`.
- Note lane keeps the stage word (8 cells) and truncates with an ellipsis.
- Do not touch `scripts/state.py`, `types/index.d.ts`, `hooks/hooks.json`, `.claude-plugin/*`, `README.md`, `docs/plans/2026-10-08-pboard-stage-track.md`.
- Do not refactor, rename or reformat anything the tasks below do not name.

## Review Focus

Inputs the spec implies but no mock shows. Each has a test in the task that owns it.

1. **Mission with no badge** (every stage `pending`, no attention): marker is a dim `·`, never an empty string that collapses the lane. Task 1 (`markerOf(undefined)`), Task 3 (mount finds `'· '`).
2. **Long or unknown stage word**: lane is fixed at 8 cells; `worktree` shows as `tree`; longer words are cut to 8. Task 1.
3. **`stage: 'ready'`**: lane reads `pr`, as the mock shows for ORC-420. Task 1.
4. **Long ticket** (> 8 chars): `ticketWidth = max(9, longest + 1)` keeps one lane across rows. Task 3 mount test with a 13-char ticket.
5. **Note wider than the lane**: the note `Text` has `wrap="truncate-end"` inside a `flexGrow: 1` `Box`; the switch button stays on the row. Task 3 mount test.

---

## File map

| File | Change |
| --- | --- |
| `hooks/register.tsx` | New pure `stageWordOf`, `markerOf`; `Row` loses `track`, gains `stage` + `marker`; new render; delete `ui.focus` hook, `focusedId`, `SELECTED`, `LETTERS`, `GLYPH`, `COLOR`, `BADGE_STYLE`, `BADGE_WIDTH` |
| `hooks/board.test.ts` | Replace 2 tests, delete 1, add 4 |
| `skills/pipeline/SKILL.md` § Board | Rewrite the first four sentences |

Kept unchanged: `PANE`, `STAGES`, `isClosed`, `toneOf`, `trackOf`, `badgeOf`, `ageOf`, `switchArgv`, `switchTo`, `load`, `rootOf`, `session.start` and `command.run` hooks, empty state.

## Interfaces

```ts
// Unchanged
export type Track = StageStatus[]
export type BadgeTone = 'ask' | 'fail' | 'merge' | 'work'
export type Badge = { word: string; tone: BadgeTone }
export function trackOf(m: Mission): Track
export function badgeOf(m: Mission): Badge | undefined
export function ageOf(updated: string, now: number): string

// New (Task 1)
export function stageWordOf(m: Mission): string
export type Marker = { glyph: string; tone?: BadgeTone }
export function markerOf(badge: Badge | undefined): Marker

// Changed (Task 2)
export type Row = {            // final shape after Task 3; Task 2 still carries `track: Track`
  id: string
  ticket: string
  tone: MissionTone
  stage: string
  badge?: Badge
  marker: Marker
  note: string
  terminal?: string
  hotkey?: string
  age: string
}
export function rowsOf(list: Mission[], now: number): Row[]
```

### Row layout (40 cols)

```
? ORC-412  spec    Fall back to SMS…   1
! ORC-405  review  2 blocking: sess…   2
✓ ORC-420  pr      PR #88 green        3
» ORC-398  build   Wire TOTP verifi…  4m
· ORC-417  plan    Drafting offline…  1m

? asks  ! failed  ✓ merge  » working      <- legend, always
↑↓ move · ⏎ switch · 1-3 jump · esc back  <- only when isFocused
```

---

### Task 1: Pure helpers `stageWordOf` and `markerOf`

**Files:**
- Modify: `hooks/register.tsx` (after `badgeOf`, before `ageOf`)
- Test: `hooks/board.test.ts`

**Interfaces:**
- Consumes: `Mission` from `../types`, `Badge`, `BadgeTone` already in the file.
- Produces: `stageWordOf(m: Mission): string`, `type Marker`, `markerOf(badge: Badge | undefined): Marker`, module constants `STAGE_WIDTH`, `MARKER`.

- [ ] **Step 1: Write the failing tests.** Add `stageWordOf`, `markerOf` to the import line of `hooks/board.test.ts`, then add after the `badgeOf` test:

```ts
test('stageWordOf names the stage lane in at most 8 chars', () => {
  expect(stageWordOf(sample)).toBe('spec')
  expect(stageWordOf({ ...sample, stage: 'worktree' })).toBe('tree')
  expect(stageWordOf({ ...sample, stage: 'ready' })).toBe('pr')
  expect(stageWordOf({ ...sample, stage: 'integration-x' })).toBe('integrat')
  expect(stageWordOf({ ...sample, stage: '' })).toBe('')
})

test('markerOf: one glyph per badge tone, a dot without a badge', () => {
  expect(markerOf({ word: 'ASKS', tone: 'ask' })).toEqual({ glyph: '?', tone: 'ask' })
  expect(markerOf({ word: 'FAILED', tone: 'fail' })).toEqual({ glyph: '!', tone: 'fail' })
  expect(markerOf({ word: 'MERGE', tone: 'merge' })).toEqual({ glyph: '✓', tone: 'merge' })
  expect(markerOf({ word: '⋯ working', tone: 'work' })).toEqual({ glyph: '»', tone: 'work' })
  expect(markerOf(undefined)).toEqual({ glyph: '·' })
})
```

- [ ] **Step 2: Run to verify they fail.** Run: `claude plugin test .` Expected: the two new tests fail (missing exports).

- [ ] **Step 3: Implement.** In `hooks/register.tsx`, directly after the `badgeOf` function, add:

```ts
const STAGE_WIDTH = 8
const STAGE_WORD: Record<string, string> = { ready: 'pr', worktree: 'tree' }

/** Pure: the stage lane word, at most STAGE_WIDTH chars. `ready` reads `pr`, `worktree` reads `tree`. */
export function stageWordOf(m: Mission): string {
  const word = STAGE_WORD[m.stage] ?? m.stage ?? ''
  return word.slice(0, STAGE_WIDTH)
}

export type Marker = { glyph: string; tone?: BadgeTone }
const MARKER: Record<BadgeTone, string> = { ask: '?', fail: '!', merge: '✓', work: '»' }

/** Pure: the one-cell status glyph of a row; a row without a badge gets a dim dot. */
export function markerOf(badge: Badge | undefined): Marker {
  return badge ? { glyph: MARKER[badge.tone], tone: badge.tone } : { glyph: '·' }
}
```

- [ ] **Step 4: Run to verify they pass.** Run: `claude plugin test .` Expected: all pass.

- [ ] **Step 5: Commit.**

```bash
git add hooks/register.tsx hooks/board.test.ts
git commit -m "Add pure stage-word and marker helpers for the pboard marker lane"
```

---

### Task 2: `Row` shape and `rowsOf`

**Files:**
- Modify: `hooks/register.tsx` (`Row` type, `rowsOf`)
- Test: `hooks/board.test.ts`

**Interfaces:**
- Consumes: `stageWordOf`, `markerOf`, `Marker` from Task 1.
- Produces: `Row` with `stage: string` and `marker: Marker` added (`track` still present until Task 3). `rowsOf` signature unchanged.

- [ ] **Step 1: Write the failing test.** Add after `rowsOf note falls back …`:

```ts
test('rowsOf carries the stage word and the marker', () => {
  const [row] = rowsOf([sample], 0)
  expect(row?.stage).toBe('spec')
  expect(row?.marker).toEqual({ glyph: '?', tone: 'ask' })
  const running = rowsOf([{ ...sample, stage: 'build', stages: { ...sample.stages, spec: { status: 'done' }, build: { status: 'active' } } }], 0)[0]
  expect(running?.stage).toBe('build')
  expect(running?.marker).toEqual({ glyph: '»', tone: 'work' })
  expect(rowsOf([{ ...sample, stages: {} }], 0)[0]?.marker).toEqual({ glyph: '·' })
})
```

- [ ] **Step 2: Run to verify it fails.** Run: `claude plugin test .` Expected: fails on `stage` / `marker` undefined.

- [ ] **Step 3: Implement.** In the `Row` type, keep `track: Track` for now (Task 3 removes it together with the render that reads it) and add, after `tone: MissionTone`:

```ts
  /** The stage lane word, see stageWordOf. */
  stage: string
```

and after `badge?: Badge`:

```ts
  marker: Marker
```

In `rowsOf`, replace the `.map(m => ({ … }))` block with:

```ts
    .map(m => {
      const badge = badgeOf(m)
      return {
        id: m.id,
        ticket: m.ticket || m.id,
        tone: toneOf(m),
        track: trackOf(m),
        stage: stageWordOf(m),
        badge,
        marker: markerOf(badge),
        note: (m.attention?.reason || m.note || m.title || '').replace(/\s*\n\s*/g, ' '),
        terminal: m.attention?.terminal || undefined,
        age: ageOf(m.updated ?? '', now),
      }
    })
```

Keep `trackOf` and `Track` exported: `badgeOf` uses them and a test pins them.

- [ ] **Step 4: Run to verify it passes.** Run: `claude plugin test .` Expected: all pass. The render still reads `row.track`, which is why `track` stays on `Row` in this task.

- [ ] **Step 5: Commit.**

```bash
git add hooks/register.tsx hooks/board.test.ts
git commit -m "Give pboard rows a stage word and a marker instead of a track"
```

---

### Task 3: Render

**Files:**
- Modify: `hooks/register.tsx` (module constants, `ui.render`, delete `ui.focus`)
- Test: `hooks/board.test.ts`

**Interfaces:**
- Consumes: `Row.stage`, `Row.marker`, `MARKER`, `STAGE_WIDTH` from Tasks 1–2; `TONE_COLOR`, `switchTo`, `rowsOf`.
- Produces: the new pane output. No new exports.

- [ ] **Step 1: Replace one test, delete one, add two.**

Replace the test `the pane draws the stage letters and the badge word` with:

```ts
test('the pane draws the marker, the stage word and the legend', async ($, on) => {
  fakeFs(on, [sample, { ...sample, id: 'wbs-2', ticket: 'WBS-2', stages: {} }])
  await $.command.run(open)
  const ui = await $.ui.mount({ plugin: 'pipeline', surface: 'terminal', component: 'Pane', requestId: PANE, props })
  expect(await ui.find({ text: '? ' })).toBeDefined()
  expect(await ui.find({ text: '· ' })).toBeDefined()
  expect(await ui.find({ text: /^spec\s*$/ })).toBeDefined()
  expect(await ui.find({ text: '? asks' })).toBeDefined()
  expect(await ui.find({ text: '» working' })).toBeDefined()
  expect(await ui.find({ text: /r s p t b v m/ })).toBeUndefined()
})

test('a long ticket and a long note keep the switch button on the row', async ($, on) => {
  const reason = 'Fall back to SMS if TOTP fails, or lock the account after three tries?'
  fakeFs(on, [{ ...sample, id: 'wbs-123456789', ticket: 'WBS-123456789', attention: { terminal: 'term_42', reason } }])
  await $.command.run(open)
  const ui = await $.ui.mount({ plugin: 'pipeline', surface: 'terminal', component: 'Pane', requestId: PANE, props: { ...props, bodyColumns: 40 } })
  expect(await ui.find({ key: 'switch:wbs-123456789' })).toBeDefined()
  const note = (await ui.findAll({ type: 'Text', text: reason }))[0]
  expect(note?.props.wrap).toBe('truncate-end')
})
```

Delete the whole test `the row whose switch holds the focus draws its whole note`.

Keep `only a focused pane draws the key footer` unchanged: its footer string stays `'↑↓ move · ⏎ switch · 1-1 jump · esc back'`.

- [ ] **Step 2: Run to verify the new tests fail.** Run: `claude plugin test .` Expected: the two new tests fail; the rest pass.

- [ ] **Step 3: Implement the render.** In `hooks/register.tsx`:

Delete these module-level declarations: `LETTERS`, `GLYPH`, `COLOR`, `BADGE_STYLE`, `BADGE_WIDTH`, `SELECTED`, and the line `let focusedId: string | undefined` together with its doc comment. In the `Row` type delete the line `track: Track`; in `rowsOf` delete the line `track: trackOf(m),`. Keep `trackOf` and `Track` exported (used by `badgeOf` and a test).

Add, next to `MARKER` from Task 1:

```ts
const MARKER_COLOR: Record<BadgeTone, string> = { ask: 'yellow', fail: 'red', merge: 'yellow', work: 'cyan' }
const LEGEND: Array<[BadgeTone, string]> = [['ask', 'asks'], ['fail', 'failed'], ['merge', 'merge'], ['work', 'working']]
```

Delete the whole `on('ui.focus', { requestId: PANE }, …)` hook inside `register`.

Replace the `on('ui.render', …)` hook with:

```tsx
  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const rows = rowsOf(cache, Date.now())

    if (rows.length === 0) {
      return (
        <Box flexDirection="column">
          <Text>No open missions.</Text>
          <Text dimColor>/pipeline &lt;ticket&gt; starts one.</Text>
        </Box>
      )
    }
    const ticketWidth = Math.max(9, ...rows.map(r => r.ticket.length + 1))
    const firstSwitch = rows.findIndex(r => r.terminal)
    const keys = rows.filter(r => r.hotkey).length
    return (
      <Box flexDirection="column">
        {rows.map((row, i) => {
          const running = row.tone === 'running'
          const tone = row.marker.tone
          return (
            <Box flexDirection="row" key={row.id}>
              <Text bold color={tone ? MARKER_COLOR[tone] : undefined} dimColor={!tone}>
                {`${row.marker.glyph} `}
              </Text>
              <Text bold>{row.ticket.padEnd(ticketWidth)}</Text>
              <Text dimColor={running}>{row.stage.padEnd(STAGE_WIDTH)}</Text>
              <Box flexGrow={1}>
                <Text dimColor={running} wrap="truncate-end">
                  {row.note}
                </Text>
              </Box>
              <Text> </Text>
              {row.terminal ? (
                <Button
                  key={`switch:${row.id}`}
                  hotkey={row.hotkey}
                  plain
                  autoFocus={i === firstSwitch ? true : undefined}
                  onPress={() => void switchTo($, row)}
                >
                  ⏎
                </Button>
              ) : (
                <Text dimColor>{running ? row.age : ''}</Text>
              )}
            </Box>
          )
        })}
        <Text> </Text>
        <Box flexDirection="row" gap={2}>
          {LEGEND.map(([tone, word]) => (
            <Text key={tone} color={MARKER_COLOR[tone]}>
              {`${MARKER[tone]} ${word}`}
            </Text>
          ))}
        </Box>
        {e.props.isFocused && (
          <Text dimColor>{`↑↓ move · ⏎ switch${keys ? ` · 1-${keys} jump` : ''} · esc back`}</Text>
        )}
      </Box>
    )
  })
```

Notes for the implementer:
- `TONE_COLOR` is still used by nothing after this change except `toneOf` callers? It is not. Keep the constant anyway; do not delete it (out of scope). If the type checker flags it unused and fails the run, prefix nothing and do not delete: report back instead.
- `Box` props `flexGrow`, `gap` and `Text` `wrap="truncate-end"` exist in the pane types (claude-code.d.ts: Box `flexGrow` line 957, `gap` line 963; Text `wrap` line 12511).
- The Button label is `⏎`; a plain Button with a hotkey draws `1: ⏎` by itself (claude-code.d.ts:9352). Do not pass `color` to `Button`.

- [ ] **Step 4: Run to verify all pass.** Run: `claude plugin test .` Expected: all pass, including `only a focused pane draws the key footer`, `pressing switch runs orca terminal switch`, `the pane says so when no mission exists`.

- [ ] **Step 5: Commit.**

```bash
git add hooks/register.tsx hooks/board.test.ts
git commit -m "Draw pboard rows as a marker lane with a legend"
```

---

### Task 4: Docs

**Files:**
- Modify: `skills/pipeline/SKILL.md` § Board (the paragraph starting "`/pboard` opens the pane this skill ships")

**Interfaces:** none.

- [ ] **Step 1: Replace the first four sentences.** The paragraph currently reads, up to "A row with `attention` carries a switch button.":

> `/pboard` opens the pane this skill ships (`hooks/`). One row per mission: a track of the stages `r s p t b v m` (read › spec › plan › tree › build › review › pr), filled by the state file, and one badge: `FAILED`, `ASKS`, `MERGE` (`ready`) or `⋯ working`. The second line is `attention.reason`, else `note`. Rows that need the user come first: red ticket when a stage `failed`, yellow while it waits on the user (`waiting_user`, `attention`, `ready`), then running rows with the time since `updated`. A row with `attention` carries a switch button.

Replace that span with:

> `/pboard` opens the pane this skill ships (`hooks/`). One line per mission: a status glyph (`?` asks, `!` failed, `✓` merge-ready, `»` working, `·` idle), the ticket, the stage word (`read`, `spec`, `plan`, `tree`, `build`, `review`, `pr`), then `attention.reason`, else `note`, cut to the line. Rows that need the user come first: `!` when a stage `failed`, `?` or `✓` while it waits on the user (`waiting_user`, `attention`, `ready`), then running rows with the time since `updated` at the right edge. A legend line sits under the rows. A row with `attention` carries a switch button (`1: ⏎`, its hotkey digit then Enter).

Leave the rest of the paragraph (from "A `ready` mission stays listed") unchanged.

- [ ] **Step 2: Commit.**

```bash
git add skills/pipeline/SKILL.md
git commit -m "Describe the marker-lane board in the pipeline skill"
```

---

## Tests summary (hooks/board.test.ts)

Replace: `the pane draws the stage letters and the badge word` → `the pane draws the marker, the stage word and the legend`.
Delete: `the row whose switch holds the focus draws its whole note`.
Add: `stageWordOf …`, `markerOf …`, `rowsOf carries the stage word and the marker`, `a long ticket and a long note keep the switch button on the row`.
Keep: everything else as is.

Run: `claude plugin test .`

## Spec coverage

| S element | Task |
| --- | --- |
| Marker glyph per status, colored; dim dot when idle | 1, 3 |
| Ticket bold, plain color | 3 |
| Stage word lane (8 cells); `ready` → `pr`, `worktree` → `tree` | 1, 2, 3 |
| Note truncated with ellipsis, button stays on the row | 3 |
| Hotkey digit at right edge | 3 |
| Age on running rows | 2 (kept), 3 |
| Legend line, always | 3 |
| Key hints only when focused | 3 (kept behavior) |
| Empty state | kept |
| Focused / open row state | dropped (user decision 2026-10-08) |
| Pane title "3 need you" | dropped (earlier user decision) |
