# /pboard stage track (design B2)

Design: Paper file "pboard — panel redesign", artboards `B2 · 40 columns`, `B2 · focused`,
`B2 · empty`. Approved 2026-10-08.

Goal: the pane shows each mission as a 7-stage track plus one status badge, puts the
missions that need the user at the top with hotkeys 1..n, and fits a 40-column body.

Decisions already made (do not reopen):
- Pure `trackOf()` + render; unit-test the pure parts. No state format change.
- Needs-you rows first: blocked, then asking, then running; `updated` desc inside a group.
- Active badge is a static glyph `⋯ working`. No extra timer; the 3 s poll stays the only redraw.
- No "N need you" summary line.
- Pane is always narrow (< 70 cols). The wide/narrow label split goes away.

## File map

| File | Change |
| --- | --- |
| `hooks/register.tsx` | New pure helpers, new `Row` shape, sort + hotkeys, new render, `ui.focus` hook |
| `hooks/board.test.ts` | Replace 2 tests that pin the old shape; add tests below |
| `README.md`, `skills/pipeline/SKILL.md` § Board | Update the one-paragraph board description only if it names marks (`□ ▣ ✱ ■ ✖`) |

Not touched: `scripts/state.py`, `types/index.d.ts`, `hooks/hooks.json`, plugin manifests.

## Interfaces

```ts
// Track: one entry per STAGES item, in order.
export type Track = StageStatus[]

export type BadgeTone = 'ask' | 'fail' | 'merge' | 'work'
export type Badge = { word: string; tone: BadgeTone }

/** Pure. Status per stage; a missing stage is 'pending'. */
export function trackOf(m: Mission): Track

/**
 * Pure. One badge for the row, by priority:
 *   any failed            -> { word: 'FAILED',     tone: 'fail'  }
 *   any waiting_user      -> { word: 'ASKS',       tone: 'ask'   }
 *   m.stage === 'ready'   -> { word: 'MERGE',      tone: 'merge' }
 *   any active            -> { word: '⋯ working',  tone: 'work'  }
 *   else                  -> undefined
 */
export function badgeOf(m: Mission): Badge | undefined

/** Pure. Minutes/hours/days since `updated`: '0m'..'59m', '1h'..'23h', '1d'.. ; '' if unparsable. */
export function ageOf(updated: string, now: number): string

export type Row = {
  id: string
  ticket: string
  tone: MissionTone
  track: Track
  badge?: Badge
  /** attention.reason, else note, else title. */
  note: string
  terminal?: string
  /** '1'..'9' on rows with a terminal, in display order; undefined past 9. */
  hotkey?: string
  /** Shown only on running rows. */
  age: string
}

/** Pure. Open missions only, sorted blocked > asking > running (stable), hotkeys assigned after sort. */
export function rowsOf(list: Mission[], now: number): Row[]
```

Removed: `Cell`, `LABEL`, `MARK`, the `columns` parameter of `rowsOf`.
Kept unchanged: `PANE`, `isClosed`, `toneOf`, `switchArgv`, `switchTo`, `load`, `rootOf`, `/pboard` command.

Render mapping (terminal cells, 2 per stage):

| status | glyphs | color |
| --- | --- | --- |
| done | `━━` | dimColor |
| pending | `┄┄` | dimColor (gray) |
| active | `██` | cyan |
| waiting_user | `██` | yellow |
| failed | `██` | red |

Badge: `fail` = red background, `ask`/`merge` = yellow background (black text),
`work` = cyan text, no background. Ticket color = `TONE_COLOR` for blocked/asking,
default text for running.

Row layout (40 cols): `ticket.padEnd(9)` + track (14) + 2 spaces + badge (fixed 10)
+ trailing slot: `Button hotkey plain` `[n]` when `terminal`, else `age` dim.
Line 2: 9-space indent + note, `wrap="truncate-end"`; `wrap="wrap"` when the row is the
focused one (see focus below).

Header row: 9 spaces + `r s p t b v m`, dim.

Focus:
- Module var `focusedId: string | undefined`.
- `on('ui.focus', { component: 'Pane', requestId: PANE }, ...)`: set `focusedId` from
  `e.element` when it starts with `switch:`, else undefined; `$.ui.invalidate('ui.render')`;
  return `next(e)`.
- Expanded note when `e.props.isFocused && row.id === focusedId`. Selected row gets a
  background color (`BoxProps.backgroundColor`, claude-code.d.ts:987).
- Footer when `isFocused`: `↑↓ move · ⏎ switch · 1-n jump · esc back`, dim. Replaces the old
  unfocused hint line.

Empty state: two lines, `No open missions.` and dim `/pipeline <ticket> starts one.`

## Tasks (in order)

1. **Pure helpers.** Add `trackOf`, `badgeOf`, `ageOf`. Tests first.
2. **rowsOf.** New `Row` shape, filter closed, sort by tone rank (stable), assign hotkeys,
   compute note fallback and age. Pass `Date.now()` from the render hook. Tests first.
3. **Render.** Header, rows, badge, trailing slot, empty state, footer. Drop old
   `Cell` code.
4. **Focus.** `ui.focus` hook + expanded note + selected background.
5. **Docs.** README / SKILL.md board paragraph, only where it describes the old marks.

One commit per task.

## Review focus (inputs likely to break)

- Mission with `stages` missing or `{}` → track all pending, no badge, still renders.
- Unknown stage key in `stages` (e.g. `ready`) → ignored by `trackOf` (only STAGES).
- Two stages `waiting_user`, or `failed` + `waiting_user` → badge follows priority; track
  shows both colored blocks.
- `stage: 'ready'` with `pr` still `active` → badge MERGE, not working.
- `attention` set on a running-tone mission? `toneOf` already makes it asking — hotkey follows.
- More than 9 switch rows → rows 10+ get a Button with no hotkey (as today).
- `updated` empty or bad ISO → `ageOf` returns ''.
- Long ticket (> 8 chars) → pad to `max(9, longest+1)` like today's `ticketWidth`, so the
  track stays in one lane across rows.
- Note with newlines → truncate-end must not break the grid; strip `\n` to space.
- `autoFocus` must still land on the first switch row after the sort.

## Tests (hooks/board.test.ts)

Replace:
- `rowsOf marks each stage by its status` → `trackOf returns one status per stage`.
- `rowsOf shortens labels on a narrow body` → delete (feature removed).

Add (unit):
- `badgeOf` priority: failed > waiting_user > ready > active > none.
- `ageOf`: 0m, 59m, 1h, 1d, bad input → ''.
- `rowsOf` sorts blocked, asking, running and keeps `updated` order inside a group.
- `rowsOf` gives hotkeys 1..n only to rows with a terminal, in display order.
- `rowsOf` note falls back attention.reason → note → title.
- `trackOf` with missing `stages`.

Keep and update for the new props (pane mount tests): one row per mission, hides closed,
switch press runs orca, focused pane draws no focus hint → now "unfocused pane draws no
footer", `/pboard` asks for the keyboard, no attention → no switch, empty state text.

Add (pane mount, cheap — no widget/e2e):
- badge word visible (`ASKS`) for the sample mission.
- after a `ui.focus` on `switch:<id>`, the full note is drawn.

Run: `claude plugin test .` (unit + mount tests in this file only).

## Spec coverage

| B2 element | Task |
| --- | --- |
| Stage letters header | 3 |
| Track glyphs per status | 1, 3 |
| Badge words + colors | 1, 3 |
| Needs-you first + [n] keys | 2, 3 |
| Age on running rows | 1, 2, 3 |
| Question text as note | 2 |
| Focused: expanded note, selected row, footer | 4 |
| Empty state | 3 |
| Pane title count | dropped (user decision) |
| Animated spinner | dropped (user decision) |
