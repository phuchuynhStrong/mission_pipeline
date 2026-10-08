import type { EngineInterface, Register } from 'claude-code'

import type { Mission, StageStatus } from '../types'

export const PANE = 'pipeline-board'
let cache: Mission[] = []

const STAGES = ['read', 'spec', 'plan', 'worktree', 'build', 'review', 'pr'] as const
/** The header over the track: one letter per stage, two cells each. */
const LETTERS = 'r s p t b v m '
const GLYPH: Record<StageStatus, string> = {
  done: '━━',
  pending: '┄┄',
  active: '██',
  waiting_user: '██',
  failed: '██',
}
const COLOR: Partial<Record<StageStatus, string>> = {
  active: 'cyan',
  waiting_user: 'yellow',
  failed: 'red',
}

/** How a mission reads as a whole: blocked (red) > asking (yellow) > running (green). */
export type MissionTone = 'running' | 'asking' | 'blocked'
const TONE_COLOR: Record<MissionTone, string> = {
  running: 'green',
  asking: 'yellow',
  blocked: 'red',
}

const TONE_RANK: Record<MissionTone, number> = { blocked: 0, asking: 1, running: 2 }
/** Badge styles: a filled block for what needs the user, plain cyan for work in progress. */
const BADGE_STYLE: Record<BadgeTone, { color: string; backgroundColor?: string }> = {
  fail: { color: 'black', backgroundColor: 'red' },
  ask: { color: 'black', backgroundColor: 'yellow' },
  merge: { color: 'black', backgroundColor: 'yellow' },
  work: { color: 'cyan' },
}
const BADGE_WIDTH = 10
const SELECTED = '#2A2D32'

export type Row = {
  id: string
  ticket: string
  tone: MissionTone
  track: Track
  badge?: Badge
  /** The attention reason, else the note, else the title; on one line. */
  note: string
  /** The Orca terminal handle the user should switch to, when the mission waits on them. */
  terminal?: string
  /** '1'..'9' on rows with a terminal, in display order. */
  hotkey?: string
  /** Time since the last update; the board shows it on running rows. */
  age: string
}

/** One status per STAGES item, in order. */
export type Track = StageStatus[]
export type BadgeTone = 'ask' | 'fail' | 'merge' | 'work'
export type Badge = { word: string; tone: BadgeTone }

/** Pure: the status of each pipeline stage; a missing stage is pending. */
export function trackOf(m: Mission): Track {
  return STAGES.map(name => (m.stages?.[name]?.status ?? 'pending') as StageStatus)
}

/** Pure: the one badge a row shows. failed > waiting_user > ready (merge) > active > none. */
export function badgeOf(m: Mission): Badge | undefined {
  const track = trackOf(m)
  if (track.includes('failed')) return { word: 'FAILED', tone: 'fail' }
  if (track.includes('waiting_user')) return { word: 'ASKS', tone: 'ask' }
  if (m.stage === 'ready') return { word: 'MERGE', tone: 'merge' }
  if (track.includes('active')) return { word: '⋯ working', tone: 'work' }
  return undefined
}

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

/** Pure: time since `updated` as 0m..59m, 1h..23h, 1d..; empty when `updated` does not parse. */
export function ageOf(updated: string, now: number): string {
  const at = Date.parse(updated)
  if (Number.isNaN(at)) return ''
  const minutes = Math.max(0, Math.floor((now - at) / 60000))
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h`
  return `${Math.floor(hours / 24)}d`
}

const TERMINAL = new Set(['done', 'aborted'])

/** Pure: a mission the coordinator no longer drives. */
export function isClosed(m: Mission): boolean {
  return TERMINAL.has(m.stage)
}

/**
 * Pure: the tone of one mission. Any `failed` stage is blocked. A `waiting_user` stage, an
 * `attention` handle, or the `ready` stage (PR not yet merged) is asking. Otherwise running.
 */
export function toneOf(m: Mission): MissionTone {
  const statuses = Object.values(m.stages ?? {}).map(s => s?.status)
  if (statuses.includes('failed')) return 'blocked'
  if (statuses.includes('waiting_user') || m.attention?.terminal || m.stage === 'ready') return 'asking'
  return 'running'
}

/**
 * Pure: state rows to board rows. Closed (done or aborted) missions are left out; the rest
 * sort blocked, then asking, then running, keeping the incoming order inside a tone. Rows
 * with a terminal get hotkeys 1..9 in that order.
 */
export function rowsOf(list: Mission[], now: number): Row[] {
  const rows: Row[] = list
    .filter(m => !isClosed(m))
    .map(m => ({
      id: m.id,
      ticket: m.ticket || m.id,
      tone: toneOf(m),
      track: trackOf(m),
      badge: badgeOf(m),
      note: (m.attention?.reason || m.note || m.title || '').replace(/\s*\n\s*/g, ' '),
      terminal: m.attention?.terminal || undefined,
      age: ageOf(m.updated ?? '', now),
    }))
    .sort((a, b) => TONE_RANK[a.tone] - TONE_RANK[b.tone])
  let key = 0
  for (const row of rows) {
    if (row.terminal && key < 9) row.hotkey = String(++key)
  }
  return rows
}

/** Pure: the argv that brings the user to a worker's terminal. */
export function switchArgv(terminal: string): string[] {
  return ['orca', 'terminal', 'switch', '--terminal', terminal, '--json']
}

async function switchTo($: EngineInterface, row: Row) {
  if (!row.terminal) return
  // Say the press landed before the command runs, so a silent orca failure is still visible.
  $.ui.toast(`${row.ticket}: switching to ${row.terminal}…`, { timeoutMs: 2000 })
  try {
    const { exitCode, stderr, stdout } = await $.process.run(switchArgv(row.terminal), { timeoutMs: 15000 })
    if (exitCode === 0) {
      $.ui.toast(`${row.ticket}: switched to ${row.terminal}`)
    } else {
      $.ui.toast(`${row.ticket}: orca terminal switch failed (${exitCode}): ${(stderr || stdout).trim().slice(0, 160)}`)
    }
  } catch (err) {
    $.ui.toast(`${row.ticket}: could not run orca: ${err instanceof Error ? err.message : String(err)}`)
  }
}

const POLL_MS = 3000
let lastSeen = ''
/** The mission whose switch Button holds the pane's focus ring; its note is drawn whole. */
let focusedId: string | undefined

async function rootOf($: EngineInterface, option: string): Promise<string | undefined> {
  if (option.startsWith('/')) return option
  if (option) return `${$.plugin.root}/${option}`
  const home = await $.env.get('HOME')
  return home ? `${home}/.claude/pipeline` : undefined
}

async function load($: EngineInterface, option: string) {
  const root = await rootOf($, option)
  if (!root) return
  if (!(await $.fs.exists(root))) return
  const found: Mission[] = []
  for (const repo of await $.fs.list(root)) {
    if (repo.kind !== 'dir') continue
    for (const file of await $.fs.list(`${root}/${repo.name}`)) {
      if (file.kind !== 'file' || !file.name.endsWith('.json')) continue
      try {
        found.push(JSON.parse(await $.fs.read(`${root}/${repo.name}/${file.name}`)) as Mission)
      } catch {
        // a half-written file; the next poll reads it whole
      }
    }
  }
  found.sort((a, b) => (b.updated ?? '').localeCompare(a.updated ?? ''))
  const key = JSON.stringify(found)
  if (key === lastSeen) return
  lastSeen = key
  cache = found
  $.ui.invalidate('ui.render')
}

export const register: Register = (on, options) => {
  const rootOption = typeof options.root === 'string' ? options.root : ''
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'pboard', description: 'Open the pipeline mission board' })
    await load($, rootOption)
    $.clock.every(POLL_MS, () => void load($, rootOption))
    const open = cache.some(m => !isClosed(m))
    if (open) void $.ui.open({ id: PANE, title: 'Pipeline' })
    return next(e)
  })

  on('command.run', { command: 'pboard' }, async $ => {
    await load($, rootOption)
    // The person asked for the board: hand it the keyboard so hotkeys and Enter work at once.
    await $.ui.open({ id: PANE, title: 'Pipeline', focus: true })
    return { text: 'Pipeline board opened. ctrl+x tab focuses it; a row digit or Enter presses switch.' }
  })

  on('ui.focus', { requestId: PANE }, async ($, e, next) => {
    // Track which switch Button holds the ring, so its row can draw the whole question.
    const id = e.element?.startsWith('switch:') ? e.element.slice('switch:'.length) : undefined
    if (id !== focusedId) {
      focusedId = id
      $.ui.invalidate('ui.render')
    }
    return next(e)
  })

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
    const focused = e.props.isFocused
    return (
      <Box flexDirection="column">
        <Text dimColor>{' '.repeat(ticketWidth) + LETTERS}</Text>
        {rows.map((row, i) => {
          const open = focused && row.id === focusedId
          const badge = row.badge
          const word = badge ? (BADGE_STYLE[badge.tone].backgroundColor ? ` ${badge.word} ` : badge.word) : ''
          return (
            <Box flexDirection="column" key={row.id} backgroundColor={open ? SELECTED : undefined}>
              <Box flexDirection="row">
                <Text bold color={row.tone === 'running' ? undefined : TONE_COLOR[row.tone]}>
                  {row.ticket.padEnd(ticketWidth)}
                </Text>
                {row.track.map(status => (
                  <Text color={COLOR[status]} dimColor={!COLOR[status]}>
                    {GLYPH[status]}
                  </Text>
                ))}
                <Text> </Text>
                {badge && (
                  <Text bold={badge.tone !== 'work'} {...BADGE_STYLE[badge.tone]}>
                    {word}
                  </Text>
                )}
                <Text>{' '.repeat(Math.max(1, BADGE_WIDTH - word.length))}</Text>
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
                  <Text dimColor>{row.tone === 'running' ? row.age : ''}</Text>
                )}
              </Box>
              <Box flexDirection="row">
                <Text>{' '.repeat(ticketWidth)}</Text>
                <Text dimColor={row.tone === 'running'} wrap={open ? 'wrap' : 'truncate-end'}>
                  {row.note}
                </Text>
              </Box>
            </Box>
          )
        })}
        {focused && (
          <Text dimColor>{`↑↓ move · ⏎ switch${keys ? ` · 1-${keys} jump` : ''} · esc back`}</Text>
        )}
      </Box>
    )
  })
}
