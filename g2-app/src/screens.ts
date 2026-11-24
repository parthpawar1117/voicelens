export const LINE_CHARS = 48
export const SCREEN_LINES = 10

export interface Item {
  id: number
  chat_name: string
  kind: 'voice' | 'text'
  text: string
  duration: number | null
  received_at: string
  source: string | null
}

export function wrap(_text: string, _width: number): string[] {
  throw new Error('not implemented')
}
export function inboxScreen(_items: Item[], _selectedId: number | null): string {
  throw new Error('not implemented')
}
export function messagePages(_item: Item): number {
  throw new Error('not implemented')
}
export function messageScreen(_item: Item, _page: number): string {
  throw new Error('not implemented')
}
