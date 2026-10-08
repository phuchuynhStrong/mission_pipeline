import { test, expect } from 'claude-code/testing'
import type { On } from 'claude-code'

import { PANE, ageOf, badgeOf, isClosed, rowsOf, switchArgv, toneOf, trackOf } from './register'
import type { Mission } from '../types'

const sample: Mission = {
  id: 'wbs-12345',
  ticket: 'WBS-12345',
  title: 'secondary phone',
  repo_slug: 'JMS.FIELD.VNEXT',
  stage: 'spec',
  note: 'brainstorm with senior',
  updated: '2026-10-06T10:00:00+10:00',
  stages: {
    read: { status: 'done' },
    spec: { status: 'waiting_user' },
    plan: { status: 'pending' },
    worktree: { status: 'pending' },
    build: { status: 'pending' },
    review: { status: 'pending' },
    pr: { status: 'pending' },
  },
}

/** A fake ~/.claude/pipeline holding the given missions, one repo folder each. */
function fakeFs(on: On, list: Mission[], opens?: Array<Record<string, unknown>>) {
  const root = '/home/t/.claude/pipeline'
  on('env.get', async (_, e) => ({ value: e.name === 'HOME' ? '/home/t' : undefined }))
  on('fs.exists', async (_, e) => ({ value: e.path === root }))
  on('fs.list', async (_, e) => {
    if (e.path === root) return { value: list.map(m => ({ name: m.repo_slug, kind: 'dir' as const, size: 0, mtimeMs: 0, isLink: false })) }
    const value = list
      .filter(m => e.path === `${root}/${m.repo_slug}`)
      .map(m => ({ name: `${m.id}.json`, kind: 'file' as const, size: 1, mtimeMs: 0, isLink: false }))
    return { value }
  })
  on('fs.read', async (_, e) => {
    const m = list.find(m => e.path === `${root}/${m.repo_slug}/${m.id}.json`)
    if (!m) return { deny: `ENOENT ${e.path}` }
    return { value: JSON.stringify(m) }
  })
  on('command.run', async () => ({}))
  on('ui.open', async (_, e) => {
    opens?.push({ ...e })
    return { value: { isPlaced: true as const } }
  })
  on('ui.invalidate', async () => ({ value: undefined }))
}

const open = {
  command: 'pboard',
  args: '',
  origin: { kind: 'composer' as const },
  presentation: { isFullscreen: true, columns: 160 },
}
const props = {
  title: 'Pipeline',
  isFocused: false,
  bodyColumns: 100,
  placement: 'dock' as const,
  scroll: { offset: 0, bodyRows: 20 },
  view: {},
}

test('trackOf returns one status per stage', () => {
  expect(trackOf(sample)).toEqual(['done', 'waiting_user', 'pending', 'pending', 'pending', 'pending', 'pending'])
  expect(trackOf({ ...sample, stages: {} })).toEqual(Array(7).fill('pending'))
  expect(trackOf({ ...sample, stages: undefined as unknown as Mission['stages'] })).toEqual(Array(7).fill('pending'))
  expect(trackOf({ ...sample, stages: { ...sample.stages, ready: { status: 'active' } } })).toHaveLength(7)
})

test('badgeOf: failed beats asks beats merge beats working', () => {
  const st = (over: Mission['stages']) => ({ ...sample, stages: { ...sample.stages, ...over } })
  expect(badgeOf(st({ build: { status: 'failed' } }))).toEqual({ word: 'FAILED', tone: 'fail' })
  expect(badgeOf(sample)).toEqual({ word: 'ASKS', tone: 'ask' })
  expect(badgeOf({ ...st({ spec: { status: 'done' }, pr: { status: 'active' } }), stage: 'ready' })).toEqual({ word: 'MERGE', tone: 'merge' })
  expect(badgeOf(st({ spec: { status: 'active' } }))).toEqual({ word: '⋯ working', tone: 'work' })
  expect(badgeOf(st({ spec: { status: 'pending' } }))).toBeUndefined()
})

test('ageOf counts minutes, hours and days since updated', () => {
  const at = Date.parse('2026-10-06T10:00:00+10:00')
  expect(ageOf('2026-10-06T10:00:00+10:00', at)).toBe('0m')
  expect(ageOf('2026-10-06T10:00:00+10:00', at + 59 * 60000)).toBe('59m')
  expect(ageOf('2026-10-06T10:00:00+10:00', at + 60 * 60000)).toBe('1h')
  expect(ageOf('2026-10-06T10:00:00+10:00', at + 24 * 3600000)).toBe('1d')
  expect(ageOf('', at)).toBe('')
  expect(ageOf('not a date', at)).toBe('')
})

test('rowsOf marks each stage by its status', () => {
  const row = rowsOf([sample], 100)[0]!
  expect(row.ticket).toBe('WBS-12345')
  expect(row.cells.map(c => c.mark).join('')).toBe('■✱□□□□□')
  expect(row.note).toBe('brainstorm with senior')
})

test('a done or aborted mission is closed and left off the board', () => {
  const aborted: Mission = { ...sample, id: 'wbs-1', ticket: 'WBS-1', stage: 'aborted', note: 'ABORTED: user' }
  expect(isClosed(aborted)).toBe(true)
  expect(isClosed({ ...sample, stage: 'done' })).toBe(true)
  expect(isClosed(sample)).toBe(false)
  expect(isClosed({ ...sample, stage: 'ready' })).toBe(false)
  const done: Mission = { ...sample, id: 'wbs-2', ticket: 'WBS-2', stage: 'done', note: 'MERGED' }
  expect(rowsOf([aborted, done, sample], 100).map(r => r.ticket)).toEqual(['WBS-12345'])
})

test('toneOf: blocked beats asking beats running', () => {
  expect(toneOf({ ...sample, stages: { ...sample.stages, spec: { status: 'active' } } })).toBe('running')
  expect(toneOf(sample)).toBe('asking')
  expect(toneOf({ ...sample, stages: { ...sample.stages, spec: { status: 'active' } }, attention: { terminal: 'term_1', reason: 'x' } })).toBe('asking')
  expect(toneOf({ ...sample, stage: 'ready', stages: { ...sample.stages, spec: { status: 'done' } } })).toBe('asking')
  expect(toneOf({ ...sample, stages: { ...sample.stages, build: { status: 'failed' } } })).toBe('blocked')
})

test('rowsOf carries the attention terminal', () => {
  expect(rowsOf([sample], 100)[0]?.terminal).toBeUndefined()
  expect(rowsOf([{ ...sample, attention: { terminal: 'term_9', reason: 'r' } }], 100)[0]?.terminal).toBe('term_9')
  expect(switchArgv('term_9')).toEqual(['orca', 'terminal', 'switch', '--terminal', 'term_9', '--json'])
})

test('rowsOf shortens labels on a narrow body', () => {
  const wide = rowsOf([sample], 100)[0]!
  const narrow = rowsOf([sample], 50)[0]!
  expect(wide.cells[0]?.label).toBe('read')
  expect(narrow.cells[0]?.label).toBe('R')
})

test('the pane lists one row per mission from the state folder', async ($, on) => {
  fakeFs(on, [sample])
  await $.command.run(open)
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'pipeline', surface, component: 'Pane', requestId: PANE, props })
    expect(await ui.find({ text: 'WBS-12345' })).toBeDefined()
    expect(await ui.find({ text: 'brainstorm with senior' })).toBeDefined()
  }
})

test('the pane hides aborted and done missions', async ($, on) => {
  fakeFs(on, [
    { ...sample, stage: 'aborted', note: 'ABORTED: user stopped' },
    { ...sample, id: 'wbs-2', ticket: 'WBS-2', stage: 'done', note: 'MERGED into main' },
  ])
  await $.command.run(open)
  const ui = await $.ui.mount({ plugin: 'pipeline', surface: 'terminal', component: 'Pane', requestId: PANE, props })
  expect(await ui.find({ text: 'WBS-12345' })).toBeUndefined()
  expect(await ui.find({ text: 'ABORTED: user stopped' })).toBeUndefined()
  expect(await ui.find({ text: 'WBS-2' })).toBeUndefined()
  expect(await ui.find({ text: 'MERGED into main' })).toBeUndefined()
  expect(await ui.find({ text: 'No missions yet.' })).toBeDefined()
})

test('pressing switch runs orca terminal switch for that mission', async ($, on) => {
  fakeFs(on, [{ ...sample, attention: { terminal: 'term_42', reason: 'brainstorm with senior' } }])
  const runs: string[][] = []
  const toasts: string[] = []
  on('process.run', async (_, e) => {
    runs.push([...e.argv])
    return { value: { exitCode: 0, stdout: '{"ok":true}', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  on('ui.toast', async (_, e) => {
    toasts.push(e.text)
    return { value: undefined }
  })
  await $.command.run(open)
  for (const surface of ['terminal', 'desktop'] as const) {
    runs.length = 0
    const ui = await $.ui.mount({ plugin: 'pipeline', surface, component: 'Pane', requestId: PANE, props })
    expect(await ui.find({ text: 'switch' })).toBeDefined()
    expect(await ui.find({ text: 'ctrl+x tab focuses the board; then the row digit or Enter presses switch' })).toBeDefined()
    await ui.press({ key: 'switch:wbs-12345' })
    expect(runs).toEqual([['orca', 'terminal', 'switch', '--terminal', 'term_42', '--json']])
  }
  expect(toasts.some(t => t.includes('term_42'))).toBe(true)
})

test('a focused pane draws no focus hint', async ($, on) => {
  fakeFs(on, [{ ...sample, attention: { terminal: 'term_42', reason: 'r' } }])
  await $.command.run(open)
  const ui = await $.ui.mount({ plugin: 'pipeline', surface: 'terminal', component: 'Pane', requestId: PANE, props: { ...props, isFocused: true } })
  expect(await ui.find({ text: 'switch' })).toBeDefined()
  expect(await ui.find({ text: 'ctrl+x tab focuses the board; then the row digit or Enter presses switch' })).toBeUndefined()
})

test('/pboard asks for the keyboard', async ($, on) => {
  const opens: Array<Record<string, unknown>> = []
  fakeFs(on, [{ ...sample, attention: { terminal: 'term_42', reason: 'r' } }], opens)
  await $.command.run(open)
  expect(opens.some(o => o.id === PANE && o.focus === true)).toBe(true)
})

test('a mission without attention has no switch button', async ($, on) => {
  fakeFs(on, [sample])
  await $.command.run(open)
  const ui = await $.ui.mount({ plugin: 'pipeline', surface: 'terminal', component: 'Pane', requestId: PANE, props })
  expect(await ui.find({ text: 'switch' })).toBeUndefined()
})

test('the pane says so when no mission exists', async ($, on) => {
  fakeFs(on, [])
  await $.command.run(open)
  const ui = await $.ui.mount({ plugin: 'pipeline', surface: 'terminal', component: 'Pane', requestId: PANE, props })
  expect(await ui.find({ text: 'No missions yet.' })).toBeDefined()
})
