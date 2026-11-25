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
import { DIGEST_ID, inboxScreen, messagePages, messageScreen, wrap, LINE_CHARS, SCREEN_LINES, type Item } from './screens'

export { DIGEST_ID }

export type ReplyFormat = 'voice' | 'text'

export interface ReplyDraft {
  draftId: string
  text: string
  format: ReplyFormat
  chatName: string
  voiceAvailable?: boolean // false for a quick reply with no recording
  quick?: boolean // made from a saved quick reply
  command?: boolean // a new message from a voice command, not a reply
}

export interface Nav {
  screen: 'inbox' | 'message' | 'quick' | 'digest' | 'recording' | 'thinking' | 'confirm' | 'sending' | 'sent' | 'error' | 'exit'
  selectedId: number | null
  page: number
  quickIndex?: number // row in the reply card: AI drafts, then "Record voice note", then quick replies
  quickId?: string // set while a quick-reply draft is being prepared
  draftText?: string // set while an AI draft is being prepared for approval
  popup?: boolean // reply card opened by a new message arriving
  command?: boolean // recording / preparing a voice command ("send a message to Mom: ...")
  digest?: string[] // digest lines, once loaded
  reply?: ReplyDraft & { countdown: number }
  error?: string
}

export type AppEvent =
  | { type: 'draft'; draft: ReplyDraft }
  | { type: 'tick' }
  | { type: 'sent' }
  | { type: 'done' }
  | { type: 'error'; message: string }
  | { type: 'incoming'; id: number } // a new message arrived
  | { type: 'digest'; lines: string[] }

export const COUNTDOWN_S = 5
const QUICK_ROWS = 6 // rows visible at once (header + rows + footer <= SCREEN_LINES)

export function initialNav(items: Item[]): Nav {
  return { screen: 'inbox', selectedId: items[0]?.id ?? null, page: 0 }
}

// Back from a reply flow: to the message, or to the inbox for a command or pop-up.
const backToMessage = (s: Nav): Nav =>
  s.command || s.reply?.command || s.popup
    ? { screen: 'inbox', selectedId: s.selectedId, page: 0 }
    : { screen: 'message', selectedId: s.selectedId, page: 0 }

function moveSelection(s: Nav, items: Item[], step: number): Nav {
  const ids = [DIGEST_ID, ...items.map(i => i.id)] // the digest row sits above the newest message
  const at = ids.indexOf(s.selectedId ?? ids[1] ?? DIGEST_ID)
  const next = Math.min(Math.max(0, (at < 0 ? 1 : at) + step), ids.length - 1)
  return { ...s, selectedId: ids[next] }
}

type Row = { kind: 'ai'; text: string } | { kind: 'record' } | { kind: 'quick'; reply: QuickReply }

export function cardRows(item: Item | undefined, quick: QuickReply[]): Row[] {
  return [...(item?.drafts ?? []).map(text => ({ kind: 'ai' as const, text })), { kind: 'record' as const },
    ...quick.map(reply => ({ kind: 'quick' as const, reply }))]
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
      return { screen: 'error', selectedId: s.selectedId, page: 0, error: e.message, command: s.command || s.reply?.command }
    case 'incoming':
      // Pop up only from the inbox: never interrupt reading or replying.
      return s.screen === 'inbox' ? { screen: 'quick', selectedId: e.id, page: 0, quickIndex: 0, popup: true } : s
    case 'digest':
      return s.screen === 'digest' ? { ...s, digest: e.lines } : s
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
        case 'tap':
          if (s.selectedId === DIGEST_ID) return { screen: 'digest', selectedId: DIGEST_ID, page: 0 }
          return s.selectedId === null ? s : { screen: 'message', selectedId: s.selectedId, page: 0 }
        case 'long_press': return { screen: 'recording', selectedId: s.selectedId, page: 0, command: true }
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
      const rows = cardRows(items.find(i => i.id === s.selectedId), quick)
      const at = Math.min(s.quickIndex ?? 0, rows.length - 1)
      const base = { selectedId: s.selectedId, page: 0, popup: s.popup }
      switch (g) {
        case 'swipe_down': return { ...s, quickIndex: Math.min(at + 1, rows.length - 1) }
        case 'swipe_up': return { ...s, quickIndex: Math.max(at - 1, 0) }
        case 'double_tap': return backToMessage(s)
        case 'long_press': return { screen: 'recording', ...base }
        case 'tap': {
          const row = rows[at]
          if (row.kind === 'ai') return { screen: 'thinking', ...base, draftText: row.text }
          if (row.kind === 'quick') return { screen: 'thinking', ...base, quickId: row.reply.id }
          return { screen: 'recording', ...base }
        }
        default: return s
      }
    }

    case 'digest':
      return g === 'double_tap' ? { screen: 'inbox', selectedId: DIGEST_ID, page: 0 } : s

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

function quickScreen(s: Nav, item: Item | undefined, to: string, quick: QuickReply[]): string {
  // Label then a short tag, no space-padding: the G2 font is proportional,
  // so padded columns drift.
  const rows = cardRows(item, quick).map(r =>
    r.kind === 'ai' ? `${clip(r.text, LINE_CHARS - 4 - 5)} (AI)`
      : r.kind === 'record' ? '(o) Record voice note'
        : r.reply.has_voice ? `${clip(r.reply.label, LINE_CHARS - 4 - 8)} (voice)` : clip(r.reply.label, LINE_CHARS - 4))
  const head = s.popup && item
    ? [clip(`New from ${to}`, LINE_CHARS), ...wrap(item.text, LINE_CHARS).slice(0, 2)]
    : [clip(`Reply to ${to}`, LINE_CHARS)]
  const visible = Math.min(QUICK_ROWS, SCREEN_LINES - head.length - 1)
  const at = Math.min(s.quickIndex ?? 0, rows.length - 1)
  const start = Math.min(Math.max(0, at - (visible - 1)), Math.max(0, rows.length - visible))
  const shown = rows.slice(start, start + visible).map((r, i) => `${start + i === at ? '>' : ' '} ${r}`)
  return [...head, ...shown, 'swipe: choose | tap: send | dbl-tap: back'].join('\n')
}

export function render(s: Nav, items: Item[], quick: QuickReply[] = []): string {
  const item = items.find(i => i.id === s.selectedId)
  const to = s.reply?.chatName ?? item?.chat_name ?? ''
  switch (s.screen) {
    case 'message':
      if (item) return messageScreen(item, s.page)
      break
    case 'quick':
      return quickScreen(s, item, to, quick)
    case 'digest':
      return ['Digest of your chats', '',
        ...(s.digest === undefined ? ['Making your digest...'] : s.digest.length ? s.digest.map(l => clip(`- ${l}`, LINE_CHARS)) : ['Nothing new in your picked chats.']),
        '', 'dbl-tap: back'].slice(0, SCREEN_LINES).join('\n')
    case 'recording':
      if (s.command) {
        return ['Voice command', '', '(o) Recording... say:', '"Send a message to <name>: <text>"', 'or "Voice note to <name>: ..."', '', 'release (or tap) to finish', 'dbl-tap: cancel'].join('\n')
      }
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
      return [r.command ? `New message to ${to}` : `Reply to ${to}`, r.quick ? 'Quick reply:' : 'You said:', ...said,
        `${mark('text')} ^ TEXT          (swipe up)`, `${mark('voice')} v VOICE NOTE    ${voiceHint}`, status].join('\n')
    }
    case 'sent':
      return [`Sent to ${to}`, '', `as ${formatName(s.reply?.format ?? 'text')}`, '', 'Back to inbox...'].join('\n')
    case 'error':
    {
      const why = (s.error ?? 'Something went wrong').replace(/^./, c => c.toUpperCase())
      return ['Reply not sent', '', ...wrap(why, LINE_CHARS).slice(0, 4), '', 'tap: back to message'].join('\n')
    }
  }
  return inboxScreen(items, s.selectedId)
}
