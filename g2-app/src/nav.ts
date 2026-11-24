import type { Gesture } from './gestures'
import type { Item } from './screens'

export interface Nav {
  screen: 'inbox' | 'message' | 'exit'
  selectedId: number | null
  page: number
}

export function initialNav(_items: Item[]): Nav {
  throw new Error('not implemented')
}
export function reduce(_s: Nav, _g: Gesture, _items: Item[]): Nav {
  throw new Error('not implemented')
}
export function render(_s: Nav, _items: Item[]): string {
  throw new Error('not implemented')
}
