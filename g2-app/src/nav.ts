// Navigation as a pure state machine: (state, gesture, items) -> state.
// Selection is tracked by message id, not position, so it stays on the same
// message when a new one arrives at the top of the list.
//
// Gestures: swipe = move (harmless if a tap is misread as a swipe),
// tap = open, double tap = back (or exit from the inbox).

import type { Gesture } from './gestures'
import { inboxScreen, messagePages, messageScreen, type Item } from './screens'

export interface Nav {
  screen: 'inbox' | 'message' | 'exit'
  selectedId: number | null
  page: number
}

export function initialNav(items: Item[]): Nav {
  return { screen: 'inbox', selectedId: items[0]?.id ?? null, page: 0 }
}

function moveSelection(s: Nav, items: Item[], step: number): Nav {
  if (items.length === 0) return { ...s, selectedId: null }
  const at = items.findIndex(i => i.id === s.selectedId)
  const next = Math.min(Math.max(0, (at < 0 ? 0 : at) + step), items.length - 1)
  return { ...s, selectedId: items[next].id }
}

export function reduce(s: Nav, g: Gesture, items: Item[]): Nav {
  if (s.screen === 'message') {
    const item = items.find(i => i.id === s.selectedId)
    if (!item) return { screen: 'inbox', selectedId: items[0]?.id ?? null, page: 0 }
    const last = messagePages(item) - 1
    switch (g) {
      case 'swipe_down': return { ...s, page: Math.min(s.page + 1, last) }
      case 'swipe_up': return { ...s, page: Math.max(s.page - 1, 0) }
      case 'double_tap': return { screen: 'inbox', selectedId: s.selectedId, page: 0 }
      default: return s // tap / hold: reply arrives on Day 3
    }
  }
  if (s.screen === 'inbox') {
    switch (g) {
      case 'swipe_down': return moveSelection(s, items, +1)
      case 'swipe_up': return moveSelection(s, items, -1)
      case 'tap': return s.selectedId === null ? s : { screen: 'message', selectedId: s.selectedId, page: 0 }
      case 'double_tap': return { ...s, screen: 'exit' }
      default: return s
    }
  }
  return s
}

export function render(s: Nav, items: Item[]): string {
  if (s.screen === 'message') {
    const item = items.find(i => i.id === s.selectedId)
    if (item) return messageScreen(item, s.page)
  }
  return inboxScreen(items, s.selectedId)
}
