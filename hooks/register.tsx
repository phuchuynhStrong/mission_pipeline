import type { EngineInterface, Register } from 'claude-code'

import type { Mission, StageStatus } from '../types'

export const PANE = 'pipeline-board'
let cache: Mission[] = []

const STAGES = ['read', 'spec', 'plan', 'worktree', 'build', 'review'] as const
const LABEL: Record<string, [wide: string, narrow: string]> = {
  read: ['read', 'R'],
  spec: ['spec', 'S'],
  plan: ['plan', 'P'],
  worktree: ['tree', 'T'],
  build: ['build', 'B'],
  review: ['review', 'V'],
}
const MARK: Record<StageStatus, string> = {
  pending: '□',
  active: '▣',
  waiting_user: '✱',
  done: '■',
  failed: '✖',
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

export type Cell = { label: string; mark: string; status: StageStatus }
export type Row = {
  id: string
  ticket: string
  title: string
  cells: Cell[]
  note: string
  tone: MissionTone
  /** The Orca terminal handle the user should switch to, when the mission waits on them. */
  terminal?: string
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

/** Pure: state rows to board rows; closed (done or aborted) missions are left out. `columns` is the pane body width in cells. */
export function rowsOf(list: Mission[], columns: number): Row[] {
  const narrow = columns < 70
  return list.filter(m => !isClosed(m)).map(m => ({
    id: m.id,
    ticket: m.ticket || m.id,
    title: m.title,
    note: m.note,
    tone: toneOf(m),
    terminal: m.attention?.terminal || undefined,
    cells: STAGES.map(name => {
      const status = (m.stages?.[name]?.status ?? 'pending') as StageStatus
      const label = LABEL[name]
      return { label: (narrow ? label?.[1] : label?.[0]) ?? name, mark: MARK[status] ?? '□', status }
    }),
  }))
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
    await $.command.register({ name: 'pipeline-board', description: 'Open the pipeline mission board' })
    await load($, rootOption)
    $.clock.every(POLL_MS, () => void load($, rootOption))
    const open = cache.some(m => !isClosed(m))
    if (open) void $.ui.open({ id: PANE, title: 'Pipeline' })
    return next(e)
  })

  on('command.run', { command: 'pipeline-board' }, async $ => {
    await load($, rootOption)
    // The person asked for the board: hand it the keyboard so hotkeys and Enter work at once.
    await $.ui.open({ id: PANE, title: 'Pipeline', focus: true })
    return { text: 'Pipeline board opened. ctrl+x tab focuses it; a row digit or Enter presses switch.' }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const rows = rowsOf(cache, e.props.bodyColumns ?? 80)
    const ticketWidth = Math.max(8, ...rows.map(r => r.ticket.length))
    const firstSwitch = rows.findIndex(r => r.terminal)
    const showHint = firstSwitch >= 0 && !e.props.isFocused

    if (rows.length === 0) {
      return (
        <Box flexDirection="column">
          <Text dimColor>No missions yet.</Text>
        </Box>
      )
    }
    return (
      <Box flexDirection="column">
        {rows.map((row, i) => (
          <Box flexDirection="column" key={row.ticket}>
            <Box flexDirection="row" columnGap={1}>
              <Text bold color={TONE_COLOR[row.tone]}>{row.ticket.padEnd(ticketWidth)}</Text>
              {row.cells.map(cell => (
                <Text color={COLOR[cell.status]} dimColor={cell.status === 'pending'}>
                  {cell.label} {cell.mark}
                </Text>
              ))}
              {row.terminal && (
                <Button
                  key={`switch:${row.id}`}
                  hotkey={i < 9 ? String(i + 1) : undefined}
                  plain
                  autoFocus={i === firstSwitch ? true : undefined}
                  onPress={() => void switchTo($, row)}
                >
                  switch
                </Button>
              )}
            </Box>
            <Box flexDirection="row">
              <Text>{' '.repeat(ticketWidth + 1)}</Text>
              <Text dimColor wrap="truncate-end">{row.note || row.title}</Text>
            </Box>
          </Box>
        ))}
        {showHint && (
          <Text dimColor>ctrl+x tab focuses the board; then the row digit or Enter presses switch</Text>
        )}
      </Box>
    )
  })
}
