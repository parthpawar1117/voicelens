import { describe, expect, it } from 'vitest'
import { initialNav, reduce, render, type Nav } from './nav'
import type { Item } from './screens'

const mk = (id: number, text = 'hi'): Item => ({ id, chat_name: `Chat ${id}`, kind: 'text', text, duration: null, received_at: '21:00', source: null })
const items = [mk(3), mk(2), mk(1)] // newest first

describe('inbox navigation', () => {
  it('starts on the inbox with the newest message selected', () => {
    expect(initialNav(items)).toEqual({ screen: 'inbox', selectedId: 3, page: 0 })
  })

  it('swipe down moves to the next (older) message and stops at the end', () => {
    let s: Nav = initialNav(items)
    s = reduce(s, 'swipe_down', items)
    expect(s.selectedId).toBe(2)
    s = reduce(reduce(s, 'swipe_down', items), 'swipe_down', items)
    expect(s.selectedId).toBe(1)
  })

  it('swipe up moves back and stops at the top', () => {
    const s = reduce(initialNav(items), 'swipe_up', items)
    expect(s.selectedId).toBe(3)
  })

  it('tap opens the selected message on page 1', () => {
    const s = reduce({ screen: 'inbox', selectedId: 2, page: 0 }, 'tap', items)
    expect(s).toEqual({ screen: 'message', selectedId: 2, page: 0 })
  })

  it('double tap on the inbox jumps to the newest message and never exits the app', () => {
    const s = reduce({ screen: 'inbox', selectedId: 1, page: 0 }, 'double_tap', items)
    expect(s).toEqual({ screen: 'inbox', selectedId: 3, page: 0 })
  })

  it('selection follows the same message when a new one arrives', () => {
    const s: Nav = { screen: 'inbox', selectedId: 2, page: 0 }
    const withNew = [mk(4), ...items]
    expect(reduce(s, 'swipe_down', withNew).selectedId).toBe(1)
  })
})

describe('message navigation', () => {
  const long = [mk(9, 'word '.repeat(200).trim())]

  it('swipe down pages forward and stops on the last page', () => {
    let s: Nav = { screen: 'message', selectedId: 9, page: 0 }
    for (let i = 0; i < 20; i++) s = reduce(s, 'swipe_down', long)
    expect(s.page).toBeGreaterThan(0)
    expect(reduce(s, 'swipe_down', long).page).toBe(s.page)
  })

  it('double tap goes back to the inbox, keeping the selection', () => {
    const s = reduce({ screen: 'message', selectedId: 2, page: 1 }, 'double_tap', items)
    expect(s).toEqual({ screen: 'inbox', selectedId: 2, page: 0 })
  })

  it('a message that disappeared falls back to the inbox', () => {
    expect(reduce({ screen: 'message', selectedId: 42, page: 0 }, 'swipe_down', items).screen).toBe('inbox')
  })
})

describe('render', () => {
  it('draws the inbox or the open message', () => {
    expect(render({ screen: 'inbox', selectedId: 3, page: 0 }, items)).toContain('> Chat 3')
    expect(render({ screen: 'message', selectedId: 2, page: 0 }, items)).toContain('Chat 2 | text')
  })
})
