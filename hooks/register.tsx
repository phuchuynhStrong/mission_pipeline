import type { EngineInterface, Register } from 'claude-code'

import type { Mission, StageStatus } from '../types'

export const PANE = 'pipeline-board'
let cache: Mission[] = []

const STAGES = ['read', 'spec', 'plan', 'worktree', 'build', 'review', 'pr'] as const

/** How a mission reads as a whole: blocked (red) > asking (yellow) > running (green). */
export type MissionTone = 'running' | 'asking' | 'blocked'
const TONE_COLOR: Record<MissionTone, string> = {
  running: 'green',
  asking: 'yellow',
  blocked: 'red',
}

const TONE_RANK: Record<MissionTone, number> = { blocked: 0, asking: 1, running: 2 }

export type Row = {
  id: string
  ticket: string
  tone: MissionTone
  /** The stage lane word, see stageWordOf. */
  stage: string
  badge?: Badge
  marker: Marker
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

/** Pure: the one badge a row shows. failed > waiting_user > ready (merge) > attention > active > none. */
export function badgeOf(m: Mission): Badge | undefined {
  const track = trackOf(m)
  if (track.includes('failed')) return { word: 'FAILED', tone: 'fail' }
  if (track.includes('waiting_user')) return { word: 'ASKS', tone: 'ask' }
  if (m.stage === 'ready') return { word: 'MERGE', tone: 'merge' }
  // An attention handle means the coordinator waits on the user, even while a stage is still active.
  if (m.attention?.terminal) return { word: 'ASKS', tone: 'ask' }
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
const MARKER_COLOR: Record<BadgeTone, string> = { ask: 'yellow', fail: 'red', merge: 'yellow', work: 'cyan' }
const LEGEND: Array<[BadgeTone, string]> = [['ask', 'asks'], ['fail', 'failed'], ['merge', 'merge'], ['work', 'working']]

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
    .map(m => {
      const badge = badgeOf(m)
      return {
        id: m.id,
        ticket: m.ticket || m.id,
        tone: toneOf(m),
        stage: stageWordOf(m),
        badge,
        marker: markerOf(badge),
        note: (m.attention?.reason || m.note || m.title || '').replace(/\s*\n\s*/g, ' '),
        terminal: m.attention?.terminal || undefined,
        age: ageOf(m.updated ?? '', now),
      }
    })
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

/** The `--health` JSON line of scripts/search_stats.py: LSP call results and the Dart LSP share. */
export type LspHealth = {
  since: string
  lsp_ok: number
  lsp_err: number
  last_at: string | null
  last_ok: boolean | null
  last_error: string | null
  dart_lsp: number
  dart_total: number
}
export type HealthTone = 'ok' | 'err' | 'idle'
export type HealthLine = { text: string; tone: HealthTone }
const HEALTH_COLOR: Record<HealthTone, string | undefined> = { ok: 'green', err: 'red', idle: undefined }
const HEALTH_DAYS = 7
const HEALTH_MS = 10 * 60 * 1000
/** Shared by every session on the machine, in the state folder: one scan serves them all. */
const HEALTH_CACHE = 'lsp-health.json'
let health: LspHealth | undefined
let healthProblem = ''
let healthBusy = false
let healthTimer = false

/** Pure: the argv that asks the stats script for the board's health line. */
export function healthArgv(script: string, days = HEALTH_DAYS): string[] {
  return ['python3', '-I', script, '--health', '--days', String(days)]
}

/** Pure: the script's stdout as LspHealth, or undefined when it is not that shape. */
export function parseHealth(stdout: string): LspHealth | undefined {
  try {
    const h = JSON.parse(stdout) as LspHealth
    const counts = [h.lsp_ok, h.lsp_err, h.dart_lsp, h.dart_total]
    return counts.every(n => typeof n === 'number') && typeof h.since === 'string' ? h : undefined
  } catch {
    return undefined
  }
}

/**
 * Pure: the board's LSP line. Green when the last LSP call answered, red when it failed, dim
 * when nothing called LSP in the window or the script could not run; undefined before the
 * first run ends.
 */
export function healthLineOf(h: LspHealth | undefined, problem: string, now: number, days = HEALTH_DAYS): HealthLine | undefined {
  if (!h) return problem ? { text: `LSP · stats unavailable: ${problem}`, tone: 'idle' } : undefined
  if (h.last_ok === null) return { text: `LSP · no calls in ${days}d`, tone: 'idle' }
  const counts = `${h.lsp_ok} ok · ${h.lsp_err} err`
  if (h.last_ok === false) {
    return { text: `LSP ✗ ${counts} · last error: ${(h.last_error ?? '').slice(0, 60)}`, tone: 'err' }
  }
  const pct = h.dart_total ? Math.round((100 * h.dart_lsp) / h.dart_total) : 0
  const age = ageOf(h.last_at ?? '', now)
  return {
    text: `LSP ✓ ${counts} · last ${age || '?'} · Dart share ${pct}% (${h.dart_lsp}/${h.dart_total}) · ${days}d`,
    tone: 'ok',
  }
}

/** Pure: the cached health when the cache file is younger than `maxAgeMs`, else undefined. */
export function freshHealth(text: string, now: number, maxAgeMs = HEALTH_MS): LspHealth | undefined {
  try {
    const cache = JSON.parse(text) as { at?: unknown; health?: unknown }
    if (typeof cache.at !== 'number' || now - cache.at < 0 || now - cache.at >= maxAgeMs) return undefined
    return parseHealth(JSON.stringify(cache.health))
  } catch {
    return undefined
  }
}

async function readHealthCache($: EngineInterface, path: string): Promise<LspHealth | undefined> {
  try {
    return (await $.fs.exists(path)) ? freshHealth(await $.fs.read(path), Date.now()) : undefined
  } catch {
    return undefined
  }
}

async function refreshHealth($: EngineInterface, option: string) {
  if (healthBusy) return
  healthBusy = true
  try {
    const root = await rootOf($, option)
    const cachePath = root ? `${root}/${HEALTH_CACHE}` : undefined
    const cached = cachePath ? await readHealthCache($, cachePath) : undefined
    if (cached) {
      health = cached
      healthProblem = ''
      return
    }
    const script = `${$.plugin.root}/scripts/search_stats.py`
    const { exitCode, stdout, stderr } = await $.process.run(healthArgv(script), { timeoutMs: 60000 })
    const parsed = exitCode === 0 ? parseHealth(stdout) : undefined
    // Only a good result is shared; a failure stays local so the next session tries again.
    if (parsed && cachePath) {
      await $.fs.write(cachePath, JSON.stringify({ at: Date.now(), health: parsed })).catch(() => undefined)
    }
    // A failed run clears the old numbers: stale green must not hide a broken check.
    health = parsed
    healthProblem = parsed
      ? ''
      : exitCode === 0
        ? 'unreadable output'
        : `exit ${exitCode}: ${(stderr || stdout).trim().slice(0, 80)}`
  } catch (err) {
    health = undefined
    healthProblem = err instanceof Error ? err.message.slice(0, 80) : String(err).slice(0, 80)
  } finally {
    healthBusy = false
    $.ui.invalidate('ui.render')
  }
}

/** Refresh now, and every HEALTH_MS from then on; only sessions that show the board get here. */
function watchHealth($: EngineInterface, option: string): Promise<void> {
  if (!healthTimer) {
    healthTimer = true
    $.clock.every(HEALTH_MS, () => void refreshHealth($, option))
  }
  return refreshHealth($, option)
}

/**
 * Pure: PR number to PR URL, from each mission's `pr` stage, closed missions too. A number two
 * missions give different URLs (two repos) is left out: a wrong link is worse than none.
 */
export function prLinksOf(list: Mission[]): Map<number, string> {
  const urls = new Map<number, Set<string>>()
  for (const m of list) {
    const pr = m.stages?.pr
    if (!pr?.number || !/^https?:\/\//.test(pr.url ?? '')) continue
    urls.set(pr.number, (urls.get(pr.number) ?? new Set()).add(pr.url!))
  }
  const links = new Map<number, string>()
  for (const [n, set] of urls) {
    const [url] = set
    if (set.size === 1 && url) links.set(n, url)
  }
  return links
}

/** Code fences, code spans and markdown links: kept as written. */
const KEEP = /(```[\s\S]*?(?:```|$)|`[^`\n]*`|\[[^\]\n]*\]\([^)\n]*\))/
/** `#1234` standing alone: not in a word, a path, an entity (`&#12;`) or a URL fragment. */
const PR_REF = /(?<![\w/&#])#(\d+)(?!\w)/g

/** Pure: markdown with each `#N` that `links` knows turned into `[#N](url)`; the rest as it was. */
export function linkPrs(text: string, links: Map<number, string>): string {
  if (links.size === 0 || !text.includes('#')) return text
  return text
    .split(KEEP)
    .map((part, i) => (i % 2 ? part : part.replace(PR_REF, (ref, n) => {
      const url = links.get(Number(n))
      return url ? `[${ref}](${url})` : ref
    })))
    .join('')
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
    await $.command.register({ name: 'pboard', description: 'Open the pipeline mission board' })
    await load($, rootOption)
    $.clock.every(POLL_MS, () => void load($, rootOption))
    const open = cache.some(m => !isClosed(m))
    if (open) {
      void $.ui.open({ id: PANE, title: 'Pipeline' })
      void watchHealth($, rootOption)
    }
    return next(e)
  })

  on('command.run', { command: 'pboard' }, async $ => {
    await load($, rootOption)
    // The person asked for the board: hand it the keyboard so hotkeys and Enter work at once.
    await $.ui.open({ id: PANE, title: 'Pipeline', focus: true })
    // The pane is already up; the LSP line fills in when this ends (a cache hit, or one scan).
    await watchHealth($, rootOption)
    return { text: 'Pipeline board opened. ctrl+x tab focuses it; a row digit or Enter presses switch.' }
  })

  // Draw-time only: the stored reply and what the model reads keep the plain `#N`.
  on('ui.render', { component: 'AssistantMessage' }, async ($, e, next) => {
    const text = linkPrs(e.props.text, prLinksOf(cache))
    return next(text === e.props.text ? e : { ...e, props: { ...e.props, text } })
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const rows = rowsOf(cache, Date.now())
    const line = healthLineOf(health, healthProblem, Date.now())
    const healthText = line ? (
      <Text key="lsp-health" color={HEALTH_COLOR[line.tone]} dimColor={line.tone === 'idle'} wrap="truncate-end">
        {line.text}
      </Text>
    ) : null

    if (rows.length === 0) {
      return (
        <Box flexDirection="column">
          <Text>No open missions.</Text>
          <Text dimColor>/pipeline &lt;ticket&gt; starts one.</Text>
          {healthText && <Text> </Text>}
          {healthText}
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
              {/* Fixed lanes never shrink; only the note gives way to the width. */}
              <Box flexShrink={0}>
                <Text bold color={tone ? MARKER_COLOR[tone] : undefined} dimColor={!tone}>
                  {`${row.marker.glyph} `}
                </Text>
                <Text bold>{row.ticket.padEnd(ticketWidth)}</Text>
                <Text dimColor={running}>{row.stage.padEnd(STAGE_WIDTH)}</Text>
              </Box>
              <Box flexGrow={1}>
                <Text dimColor={running} wrap="truncate-end">
                  {row.note}
                </Text>
              </Box>
              <Box flexShrink={0}>
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
            </Box>
          )
        })}
        <Text> </Text>
        {healthText}
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
}
