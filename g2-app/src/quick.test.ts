import { describe, expect, it } from 'vitest'
import { reduce, render, type Nav } from './nav'
import { LINE_CHARS, SCREEN_LINES, type Item } from './screens'
import type { QuickReply } from './api'

const items: Item[] = [
  { id: 10, chat_name: 'Mom', kind: 'voice', text: 'Are you coming?', duration: 3, received_at: '21:00', source: 'local' },
]
const quick: QuickReply[] = [
  { id: 'q5', label: 'On my way', duration: 1.2, has_voice: true },
  { id: 'q1', label: "Can't talk now, I'll call you back", duration: null, has_voice: false },
  { id: 'q2', label: 'Give me 10 minutes', duration: null, has_voice: false },
]
const onMessage: Nav = { screen: 'message', selectedId: 10, page: 0 }
const fits = (screen: string) => {
  const lines = screen.split('\n')
  expect(lines.length).toBeLessThanOrEqual(SCREEN_LINES)
  for (const l of lines) expect(l.length).toBeLessThanOrEqual(LINE_CHARS)
}

describe('opening quick replies', () => {
  it('tap on a message opens the quick reply list with "Speak a reply" first', () => {
    const s = reduce(onMessage, 'tap', items, quick)
    expect(s).toMatchObject({ screen: 'quick', quickIndex: 0 })
    const screen = render(s, items, quick)
    expect(screen).toContain('> (o) Speak a reply')
    expect(screen).toContain('On my way')
    expect(screen).toContain('voice 1.2s')
    fits(screen)
  })

  it('hold still records straight away', () => {
    expect(reduce(onMessage, 'long_press', items, quick).screen).toBe('recording')
  })

  it('double tap goes back to the message', () => {
    const s = reduce(onMessage, 'tap', items, quick)
    expect(reduce(s, 'double_tap', items, quick)).toMatchObject({ screen: 'message', selectedId: 10 })
  })
})

describe('choosing', () => {
  const open = reduce(onMessage, 'tap', items, quick)

  it('swipes move the selection and stop at both ends', () => {
    let s = reduce(open, 'swipe_down', items, quick)
    expect(s.quickIndex).toBe(1)
    for (let i = 0; i < 10; i++) s = reduce(s, 'swipe_down', items, quick)
    expect(s.quickIndex).toBe(3) // Speak + 3 replies
    for (let i = 0; i < 10; i++) s = reduce(s, 'swipe_up', items, quick)
    expect(s.quickIndex).toBe(0)
  })

  it('tap on "Speak a reply" starts recording (works without long press)', () => {
    expect(reduce(open, 'tap', items, quick).screen).toBe('recording')
  })

  it('tap on a quick reply asks the server for a draft, never sends directly', () => {
    const s = reduce(reduce(open, 'swipe_down', items, quick), 'tap', items, quick)
    expect(s).toMatchObject({ screen: 'thinking', quickId: 'q5' })
  })

  it('the selected row stays visible in a long list', () => {
    const many: QuickReply[] = Array.from({ length: 12 }, (_, i) => ({ id: `q${i}`, label: `Reply number ${i}`, duration: null, has_voice: false }))
    let s = reduce(onMessage, 'tap', items, many)
    for (let i = 0; i < 12; i++) s = reduce(s, 'swipe_down', items, many)
    const screen = render(s, items, many)
    expect(screen).toContain('> Reply number 11')
    fits(screen)
  })
})

describe('quick reply preview', () => {
  const thinking: Nav = { screen: 'thinking', selectedId: 10, page: 0, quickId: 'q1' }
  const textOnly = { draftId: 'd', text: "Can't talk now, I'll call you back", format: 'text' as const, chatName: 'Mom', voiceAvailable: false, quick: true }

  it('shows "Quick reply:" and marks voice as not recorded', () => {
    const s = reduce(thinking, { type: 'draft', draft: textOnly }, items, quick)
    const screen = render(s, items, quick)
    expect(screen).toContain('Quick reply:')
    expect(screen).toContain('(not recorded)')
    expect(screen).toContain('> ^ TEXT')
    fits(screen)
  })

  it('swipe down cannot pick voice when there is no recording', () => {
    const s = reduce(thinking, { type: 'draft', draft: textOnly }, items, quick)
    expect(reduce(s, 'swipe_down', items, quick)).toEqual(s)
  })

  it('a recorded quick reply to a voice note defaults to your voice', () => {
    const recorded = { ...textOnly, text: 'On my way', format: 'voice' as const, voiceAvailable: true }
    const s = reduce({ ...thinking, quickId: 'q5' }, { type: 'draft', draft: recorded }, items, quick)
    expect(render(s, items, quick)).toContain('> v VOICE NOTE')
  })
})
