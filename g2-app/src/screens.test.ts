import { describe, expect, it } from 'vitest'
import { inboxScreen, messagePages, messageScreen, wrap, LINE_CHARS, SCREEN_LINES, type Item } from './screens'

const voice: Item = { id: 2, chat_name: 'Rahul', kind: 'voice', text: 'Brother, the meeting tomorrow has shifted to 5 o clock. Bring the laptop and charger both and tell Raul.', duration: 6, received_at: '21:05', source: 'local' }
const text: Item = { id: 1, chat_name: 'Mom', kind: 'text', text: 'Where are you? Dinner is ready.', duration: null, received_at: '21:01', source: null }

const fits = (screen: string) => {
  const lines = screen.split('\n')
  expect(lines.length).toBeLessThanOrEqual(SCREEN_LINES)
  for (const l of lines) expect(l.length).toBeLessThanOrEqual(LINE_CHARS)
}

describe('wrap', () => {
  it('breaks on spaces within the line width', () => {
    expect(wrap('aaa bbb ccc', 7)).toEqual(['aaa bbb', 'ccc'])
  })
  it('splits a word longer than the line', () => {
    expect(wrap('abcdefghij', 4)).toEqual(['abcd', 'efgh', 'ij'])
  })
  it('keeps the writer’s line breaks', () => {
    expect(wrap('one\ntwo', 20)).toEqual(['one', 'two'])
  })
})

describe('inboxScreen', () => {
  it('shows a friendly empty state', () => {
    const s = inboxScreen([], null)
    expect(s).toContain('No messages yet')
    fits(s)
  })

  it('marks the selected row and labels voice notes and texts without emoji', () => {
    const s = inboxScreen([voice, text], 2)
    expect(s).toContain('> Rahul')
    expect(s).toContain('voice 0:06')
    expect(s).toContain('  Mom')
    expect(s).toContain('text')
    expect(s).not.toMatch(/\p{Extended_Pictographic}/u)
    fits(s)
  })

  it('keeps the selected item visible when the list is long', () => {
    const many: Item[] = Array.from({ length: 12 }, (_, i) => ({ ...text, id: i + 1, chat_name: `Chat ${i + 1}` }))
    const s = inboxScreen(many, 12)
    expect(s).toContain('> Chat 12')
    fits(s)
  })
})

describe('messageScreen', () => {
  it('has a header with sender, kind and length, then the text', () => {
    const s = messageScreen(voice, 0)
    expect(s.split('\n')[0]).toContain('Rahul')
    expect(s.split('\n')[0]).toContain('voice 0:06')
    expect(s).toContain('Brother, the meeting')
    fits(s)
  })

  it('pages long text and shows the page number', () => {
    const long: Item = { ...text, text: 'word '.repeat(200).trim() }
    const pages = messagePages(long)
    expect(pages).toBeGreaterThan(1)
    const last = messageScreen(long, pages - 1)
    expect(last).toContain(`${pages}/${pages}`)
    fits(last)
  })

  it('clamps a page number that is out of range', () => {
    expect(messageScreen(text, 99)).toContain('Where are you?')
  })
})
