// Navigation as a pure state machine: (state, input, items) -> state.
// Inputs are gestures from the glasses or events from the app (draft ready,
// countdown tick, sent, error). main.ts performs the side effects (mic, HTTP)
// when the screen changes; this file only decides what happens next.
//
// Gestures: swipe = move (harmless if a tap is misread), tap = open,
// double tap = back/cancel (on the inbox: jump to newest; it never exits).
// Replies: hold (or tap) on a message to record, release (or tap) to stop.
// Nothing is sent before a 5 s countdown ends; during it, tap or swipe
// switches voice/text (never sends) and double tap cancels.

import type { Gesture } from './gestures'
import { inboxScreen, messagePages, messageScreen, wrap, LINE_CHARS, type Item } from './screens'

export type ReplyFormat = 'voice' | 'text'

export interface ReplyDraft {
  draftId: string
  text: string
  format: ReplyFormat
  chatName: string
}

export interface Nav {
  screen: 'inbox' | 'message' | 'recording' | 'thinking' | 'confirm' | 'sending' | 'sent' | 'error' | 'exit'
  selectedId: number | null
  page: number
  reply?: ReplyDraft & { countdown: number }
  error?: string
}

export type AppEvent =
  | { type: 'draft'; draft: ReplyDraft }
  | { type: 'tick' }
  | { type: 'sent' }
  | { type: 'done' }
  | { type: 'error'; message: string }

export const COUNTDOWN_S = 5

export function initialNav(items: Item[]): Nav {
  return { screen: 'inbox', selectedId: items[0]?.id ?? null, page: 0 }
}

const backToMessage = (s: Nav): Nav => ({ screen: 'message', selectedId: s.selectedId, page: 0 })

function moveSelection(s: Nav, items: Item[], step: number): Nav {
  if (items.length === 0) return { ...s, selectedId: null }
  const at = items.findIndex(i => i.id === s.selectedId)
  const next = Math.min(Math.max(0, (at < 0 ? 0 : at) + step), items.length - 1)
  return { ...s, selectedId: items[next].id }
}

function onEvent(s: Nav, e: AppEvent): Nav {
  switch (e.type) {
    case 'draft':
      return s.screen === 'thinking' ? { ...s, screen: 'confirm', reply: { ...e.draft, countdown: COUNTDOWN_S } } : s
    case 'tick':
      if (s.screen !== 'confirm' || !s.reply) return s
      return s.reply.countdown <= 1 ? { ...s, screen: 'sending' } : { ...s, reply: { ...s.reply, countdown: s.reply.countdown - 1 } }
    case 'sent':
      return s.screen === 'sending' ? { ...s, screen: 'sent' } : s
    case 'done':
      return s.screen === 'sent' ? { screen: 'inbox', selectedId: s.selectedId, page: 0 } : s
    case 'error':
      return { ...s, screen: 'error', error: e.message, reply: undefined }
  }
}

export function reduce(s: Nav, input: Gesture | AppEvent, items: Item[]): Nav {
  if (typeof input !== 'string') return onEvent(s, input)
  const g = input

  switch (s.screen) {
    case 'inbox':
      switch (g) {
        case 'swipe_down': return moveSelection(s, items, +1)
        case 'swipe_up': return moveSelection(s, items, -1)
        case 'tap': return s.selectedId === null ? s : { screen: 'message', selectedId: s.selectedId, page: 0 }
        // Never exit from here: one misplaced double tap closed the whole app.
        case 'double_tap': return { ...s, selectedId: items[0]?.id ?? null }
        default: return s
      }

    case 'message': {
      const item = items.find(i => i.id === s.selectedId)
      if (!item) return { screen: 'inbox', selectedId: items[0]?.id ?? null, page: 0 }
      const last = messagePages(item) - 1
      switch (g) {
        case 'swipe_down': return { ...s, page: Math.min(s.page + 1, last) }
        case 'swipe_up': return { ...s, page: Math.max(s.page - 1, 0) }
        case 'double_tap': return { screen: 'inbox', selectedId: s.selectedId, page: 0 }
        case 'long_press':
        case 'tap': return { screen: 'recording', selectedId: s.selectedId, page: 0 }
        default: return s
      }
    }

    case 'recording':
      if (g === 'long_press_release' || g === 'tap') return { ...s, screen: 'thinking' }
      if (g === 'double_tap') return backToMessage(s)
      return s // swipes ignored: the simulator emits stray scroll events

    case 'thinking':
      return g === 'double_tap' ? backToMessage(s) : s

    case 'confirm':
      if (!s.reply) return backToMessage(s)
      if (g === 'tap' || g === 'swipe_up' || g === 'swipe_down') {
        // Switching is harmless (it never sends), so any simple gesture does it.
        const format: ReplyFormat = s.reply.format === 'text' ? 'voice' : 'text'
        return { ...s, reply: { ...s.reply, format, countdown: COUNTDOWN_S } }
      }
      if (g === 'double_tap') return backToMessage(s)
      return s

    case 'error':
      return backToMessage(s)

    default:
      return s
  }
}

const formatName = (f: ReplyFormat) => (f === 'text' ? 'text' : 'voice')

export function render(s: Nav, items: Item[]): string {
  const item = items.find(i => i.id === s.selectedId)
  const to = s.reply?.chatName ?? item?.chat_name ?? ''
  switch (s.screen) {
    case 'message':
      if (item) return messageScreen(item, s.page)
      break
    case 'recording':
      return [`Reply to ${to}`, '', '(o) Recording... speak now', '', 'release (or tap) to finish', 'dbl-tap: cancel'].join('\n')
    case 'thinking':
      return [`Reply to ${to}`, '', 'Listening back...', 'Preparing your reply'].join('\n')
    case 'confirm':
    case 'sending': {
      const r = s.reply!
      const said = wrap(`"${r.text}"`, LINE_CHARS).slice(0, 5)
      const other = r.format === 'text' ? 'voice' : 'text'
      const status = s.screen === 'sending' ? `Sending as ${formatName(r.format)}...` : `Sending as ${formatName(r.format)} in ${r.countdown}...`
      return [`Reply to ${to}`, 'You said:', ...said, status, `tap: switch to ${other} | dbl-tap: cancel`].join('\n')
    }
    case 'sent':
      return [`Sent to ${to}`, '', `as ${formatName(s.reply?.format ?? 'text')}`, '', 'Back to inbox...'].join('\n')
    case 'error':
      return ['Reply not sent', '', ...wrap(s.error ?? 'Something went wrong', LINE_CHARS).slice(0, 4), '', 'tap: back to message'].join('\n')
  }
  return inboxScreen(items, s.selectedId)
}
