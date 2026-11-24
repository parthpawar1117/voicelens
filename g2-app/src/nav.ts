// Navigation as a pure state machine: (state, input, items, quick) -> state.
// Inputs are gestures from the glasses or events from the app (draft ready,
// countdown tick, sent, error). main.ts performs the side effects (mic, HTTP)
// when the screen changes; this file only decides what happens next.
//
// Gestures: swipe = move (harmless if a tap is misread), tap = open,
// double tap = back/cancel (on the inbox: jump to newest; it never exits).
// On a message: hold = speak a reply, tap = quick replies (saved replies sent
// silently; the list starts with "Speak a reply" so recording also works
// without long press). Nothing is sent before a 5 s countdown ends; during
// it, swipe up = text, swipe down = voice note (direction, not a toggle).

import type { QuickReply } from './api'
import type { Gesture } from './gestures'
import { inboxScreen, messagePages, messageScreen, wrap, LINE_CHARS, type Item } from './screens'

export type ReplyFormat = 'voice' | 'text'

export interface ReplyDraft {
  draftId: string
  text: string
  format: ReplyFormat
  chatName: string
  voiceAvailable?: boolean // false for a quick reply with no recording
  quick?: boolean // made from a saved quick reply
}

export interface Nav {
  screen: 'inbox' | 'message' | 'quick' | 'recording' | 'thinking' | 'confirm' | 'sending' | 'sent' | 'error' | 'exit'
  selectedId: number | null
  page: number
  quickIndex?: number // row in the quick list (0 = "Speak a reply")
  quickId?: string // set while a quick-reply draft is being prepared
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
const QUICK_ROWS = 6 // rows visible at once (header + rows + footer <= 10 lines)

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
      return s.screen === 'thinking'
        ? { screen: 'confirm', selectedId: s.selectedId, page: 0, reply: { ...e.draft, countdown: COUNTDOWN_S } }
        : s
    case 'tick':
      if (s.screen !== 'confirm' || !s.reply) return s
      return s.reply.countdown <= 1 ? { ...s, screen: 'sending' } : { ...s, reply: { ...s.reply, countdown: s.reply.countdown - 1 } }
    case 'sent':
      return s.screen === 'sending' ? { ...s, screen: 'sent' } : s
    case 'done':
      return s.screen === 'sent' ? { screen: 'inbox', selectedId: s.selectedId, page: 0 } : s
    case 'error':
      return { screen: 'error', selectedId: s.selectedId, page: 0, error: e.message }
  }
}

export function reduce(s: Nav, input: Gesture | AppEvent, items: Item[], quick: QuickReply[] = []): Nav {
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
        case 'long_press': return { screen: 'recording', selectedId: s.selectedId, page: 0 }
        case 'tap': return { screen: 'quick', selectedId: s.selectedId, page: 0, quickIndex: 0 }
        default: return s
      }
    }

    case 'quick': {
      const at = s.quickIndex ?? 0
      const last = quick.length // row 0 is "Speak a reply"
      switch (g) {
        case 'swipe_down': return { ...s, quickIndex: Math.min(at + 1, last) }
        case 'swipe_up': return { ...s, quickIndex: Math.max(at - 1, 0) }
        case 'double_tap': return backToMessage(s)
        case 'long_press': return { screen: 'recording', selectedId: s.selectedId, page: 0 }
        case 'tap': {
          if (at === 0) return { screen: 'recording', selectedId: s.selectedId, page: 0 }
          const q = quick[at - 1]
          return q ? { screen: 'thinking', selectedId: s.selectedId, page: 0, quickId: q.id } : s
        }
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
      if (g === 'swipe_up' || g === 'swipe_down') {
        // Direction = choice (not a toggle), so a double-read or misread
        // swipe can't flip it back. Choosing never sends.
        const format: ReplyFormat = g === 'swipe_up' ? 'text' : 'voice'
        if (format === s.reply.format) return s
        if (format === 'voice' && s.reply.voiceAvailable === false) return s // no recording to send
        return { ...s, reply: { ...s.reply, format, countdown: COUNTDOWN_S } }
      }
      if (g === 'double_tap') return backToMessage(s)
      return s // a tap never sends early

    case 'error':
      return backToMessage(s)

    default:
      return s
  }
}

const formatName = (f: ReplyFormat) => (f === 'text' ? 'text' : 'voice')
const clip = (t: string, n: number) => (t.length <= n ? t : t.slice(0, n - 3) + '...')

function quickScreen(s: Nav, to: string, quick: QuickReply[]): string {
  // Label then a short tag, no space-padding: the G2 font is proportional,
  // so padded columns drift. Only recorded replies get a tag.
  const rows = ['(o) Speak a reply', ...quick.map(q =>
    q.has_voice ? `${clip(q.label, LINE_CHARS - 2 - 2 - 8)} (voice)` : clip(q.label, LINE_CHARS - 2 - 2))]
  const at = Math.min(s.quickIndex ?? 0, rows.length - 1)
  const start = Math.min(Math.max(0, at - (QUICK_ROWS - 1)), Math.max(0, rows.length - QUICK_ROWS))
  const shown = rows.slice(start, start + QUICK_ROWS).map((r, i) => `${start + i === at ? '>' : ' '} ${r}`)
  return [clip(`Quick reply to ${to}`, LINE_CHARS), ...shown, 'swipe: choose | tap: send | dbl-tap: back'].join('\n')
}

export function render(s: Nav, items: Item[], quick: QuickReply[] = []): string {
  const item = items.find(i => i.id === s.selectedId)
  const to = s.reply?.chatName ?? item?.chat_name ?? ''
  switch (s.screen) {
    case 'message':
      if (item) return messageScreen(item, s.page)
      break
    case 'quick':
      return quickScreen(s, to, quick)
    case 'recording':
      return [`Reply to ${to}`, '', '(o) Recording... speak now', '', 'release (or tap) to finish', 'dbl-tap: cancel'].join('\n')
    case 'thinking':
      return s.quickId
        ? [`Reply to ${to}`, '', 'Preparing your quick reply...'].join('\n')
        : [`Reply to ${to}`, '', 'Listening back...', 'Preparing your reply'].join('\n')
    case 'confirm':
    case 'sending': {
      const r = s.reply!
      const said = wrap(`"${r.text}"`, LINE_CHARS).slice(0, 3)
      const mark = (f: ReplyFormat) => (r.format === f ? '>' : ' ')
      const what = r.format === 'text' ? 'text' : 'voice note'
      const voiceHint = r.voiceAvailable === false ? '(not recorded)' : '(swipe down)'
      const status = s.screen === 'sending' ? `Sending ${what}...` : `Sending ${what} in ${r.countdown}... | dbl-tap: cancel`
      return [`Reply to ${to}`, r.quick ? 'Quick reply:' : 'You said:', ...said,
        `${mark('text')} ^ TEXT          (swipe up)`, `${mark('voice')} v VOICE NOTE    ${voiceHint}`, status].join('\n')
    }
    case 'sent':
      return [`Sent to ${to}`, '', `as ${formatName(s.reply?.format ?? 'text')}`, '', 'Back to inbox...'].join('\n')
    case 'error':
      return ['Reply not sent', '', ...wrap(s.error ?? 'Something went wrong', LINE_CHARS).slice(0, 4), '', 'tap: back to message'].join('\n')
  }
  return inboxScreen(items, s.selectedId)
}
