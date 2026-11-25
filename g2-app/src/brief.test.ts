import { describe, expect, it } from 'vitest'
import { DIGEST_ID, initialNav, reduce, render, type Nav } from './nav'
import { LINE_CHARS, SCREEN_LINES, type Item } from './screens'
import type { QuickReply } from './api'

const items: Item[] = [
  { id: 10, chat_name: 'Rahul', kind: 'text', text: 'Are you joining the 5 pm call?', duration: null, received_at: '21:00', source: null, drafts: ['Yes, joining at 5', 'Running 10 min late'] },
  { id: 9, chat_name: 'Mom', kind: 'text', text: 'Dinner?', duration: null, received_at: '20:00', source: null },
]
const quick: QuickReply[] = [{ id: 'q1', label: 'On my way', duration: null, has_voice: false }]
const fits = (screen: string) => {
  const lines = screen.split('\n')
  expect(lines.length).toBeLessThanOrEqual(SCREEN_LINES)
  for (const l of lines) expect(l.length).toBeLessThanOrEqual(LINE_CHARS)
}
const card = (s: Nav = { screen: 'message', selectedId: 10, page: 0 }) => reduce(s, 'tap', items, quick)

describe('reply card: AI drafts first, then record, then quick replies', () => {
  it('lists the two AI drafts, then "Record voice note", then quick replies', () => {
    const screen = render(card(), items, quick)
    const rows = screen.split('\n')
    expect(rows.findIndex(r => r.includes('Yes, joining at 5'))).toBeLessThan(rows.findIndex(r => r.includes('Record voice note')))
    expect(rows.findIndex(r => r.includes('Record voice note'))).toBeLessThan(rows.findIndex(r => r.includes('On my way')))
    expect(screen).toContain('> Yes, joining at 5 (AI)')
    fits(screen)
  })

  it('tapping an AI draft asks the server for an approval draft (never sends directly)', () => {
    expect(reduce(card(), 'tap', items, quick)).toMatchObject({ screen: 'thinking', draftText: 'Yes, joining at 5' })
  })

  it('"Record voice note" starts recording', () => {
    let s = card()
    s = reduce(reduce(s, 'swipe_down', items, quick), 'swipe_down', items, quick)
    expect(reduce(s, 'tap', items, quick).screen).toBe('recording')
  })

  it('messages without drafts start on "Record voice note"', () => {
    const s = card({ screen: 'message', selectedId: 9, page: 0 })
    expect(render(s, items, quick)).toContain('> (o) Record voice note')
  })
})

describe('pop-up card for a new message', () => {
  it('a new message arriving on the inbox opens its reply card with the message shown', () => {
    const s = reduce(initialNav(items), { type: 'incoming', id: 10 }, items, quick)
    expect(s).toMatchObject({ screen: 'quick', selectedId: 10, popup: true, quickIndex: 0 })
    const screen = render(s, items, quick)
    expect(screen).toContain('New from Rahul')
    expect(screen).toContain('Are you joining the 5 pm call?')
    fits(screen)
  })

  it('double tap dismisses the pop-up back to the inbox', () => {
    const s = reduce(initialNav(items), { type: 'incoming', id: 10 }, items, quick)
    expect(reduce(s, 'double_tap', items, quick).screen).toBe('inbox')
  })

  it('does not interrupt you while you are reading or replying', () => {
    const reading: Nav = { screen: 'message', selectedId: 9, page: 0 }
    expect(reduce(reading, { type: 'incoming', id: 10 }, items, quick)).toEqual(reading)
  })
})

describe('digest', () => {
  it('the inbox has a digest row above the newest message', () => {
    const s = reduce(initialNav(items), 'swipe_up', items, quick)
    expect(s.selectedId).toBe(DIGEST_ID)
    expect(render(s, items, quick)).toContain('> [ Digest of your chats ]')
  })

  it('tap opens the digest, which loads then shows its lines', () => {
    let s = reduce({ screen: 'inbox', selectedId: DIGEST_ID, page: 0 }, 'tap', items, quick)
    expect(s.screen).toBe('digest')
    expect(render(s, items, quick)).toContain('Making your digest')
    s = reduce(s, { type: 'digest', lines: ['BTC broke 100k', 'Deploy at 6 pm'] }, items, quick)
    const screen = render(s, items, quick)
    expect(screen).toContain('- BTC broke 100k')
    fits(screen)
    expect(reduce(s, 'double_tap', items, quick)).toMatchObject({ screen: 'inbox', selectedId: DIGEST_ID })
  })
})

describe('voice commands', () => {
  it('hold on the inbox records a command', () => {
    expect(reduce(initialNav(items), 'long_press', items, quick)).toMatchObject({ screen: 'recording', command: true })
  })

  it('the preview says it is a new message, not a reply', () => {
    const thinking: Nav = { screen: 'thinking', selectedId: 10, page: 0, command: true }
    const s = reduce(thinking, { type: 'draft', draft: { draftId: 'd', text: 'reached safely', format: 'text', chatName: 'Mom', command: true } }, items, quick)
    const screen = render(s, items, quick)
    expect(screen).toContain('New message to Mom')
    expect(screen).toContain('"reached safely"')
    fits(screen)
  })

  it('the recording screen explains what to say', () => {
    const s = reduce(initialNav(items), 'long_press', items, quick)
    expect(render(s, items, quick)).toContain('Send a message to <name>')
  })
})
