// Screens for the 576x288 G2 display, as plain text for one text container.
// The firmware has one proportional font and drops characters it lacks, so
// screens use plain ASCII (no emoji, no "·" or "…"). Sizes are conservative:
// the simulator fit ~60 chars x 11 lines; we use 48 x 10.

export const LINE_CHARS = 48
export const SCREEN_LINES = 10
const BODY_LINES = SCREEN_LINES - 2 // header + footer
const ROWS_PER_SCREEN = 4 // each inbox row = name line + snippet line

export interface Item {
  id: number
  chat_name: string
  kind: 'voice' | 'text'
  text: string
  duration: number | null
  received_at: string
  source: string | null
  drafts?: string[] // AI-drafted replies from the server
}

// The inbox's digest row (above the newest message) is selected with this id.
export const DIGEST_ID = -1

export function wrap(text: string, width: number): string[] {
  const out: string[] = []
  for (const paragraph of text.split('\n')) {
    let line = ''
    for (let word of paragraph.split(/\s+/).filter(Boolean)) {
      while (word.length > width) {
        if (line) { out.push(line); line = '' }
        out.push(word.slice(0, width))
        word = word.slice(width)
      }
      if (!line) line = word
      else if (line.length + 1 + word.length <= width) line += ' ' + word
      else { out.push(line); line = word }
    }
    out.push(line)
  }
  return out
}

const clip = (s: string, n: number) => (s.length <= n ? s : s.slice(0, n - 3) + '...')

function kindLabel(item: Item): string {
  if (item.kind === 'text') return 'text'
  const d = Math.round(item.duration ?? 0)
  return `voice ${Math.floor(d / 60)}:${String(d % 60).padStart(2, '0')}`
}

export function inboxScreen(items: Item[], selectedId: number | null): string {
  if (items.length === 0) {
    return ['VoiceLens', '', 'No messages yet.', 'Texts and voice notes from your', 'picked chats will appear here.'].join('\n')
  }
  const onDigest = selectedId === DIGEST_ID
  const selected = onDigest ? -1 : Math.max(0, items.findIndex(i => i.id === selectedId))
  const start = Math.min(Math.max(0, selected - (ROWS_PER_SCREEN - 1)), Math.max(0, items.length - ROWS_PER_SCREEN))
  const count = `${items.length} message${items.length === 1 ? '' : 's'}`
  const lines = [onDigest ? '> [ Digest of your chats ]' : `  [ Digest ] | VoiceLens | ${count}`]
  for (const [offset, item] of items.slice(start, start + ROWS_PER_SCREEN).entries()) {
    const mark = start + offset === selected ? '>' : ' '
    // Separators, not space-padded columns: the G2 font is proportional, so
    // padded columns drift (seen in simulator screenshots).
    lines.push(`${mark} ${clip(item.chat_name, 24)} | ${kindLabel(item)} | ${item.received_at}`)
    lines.push(`    ${clip(item.text.replace(/\s+/g, ' '), LINE_CHARS - 4)}`)
  }
  lines.push('swipe: move | tap: open | hold: command')
  return lines.join('\n')
}

const bodyLines = (item: Item) => wrap(item.text, LINE_CHARS)

export function messagePages(item: Item): number {
  return Math.max(1, Math.ceil(bodyLines(item).length / BODY_LINES))
}

export function messageScreen(item: Item, page: number): string {
  const pages = messagePages(item)
  const p = Math.min(Math.max(0, page), pages - 1)
  const header = clip(`${clip(item.chat_name, 20)} | ${kindLabel(item)} | ${item.received_at}`, LINE_CHARS)
  const body = bodyLines(item).slice(p * BODY_LINES, (p + 1) * BODY_LINES)
  const hint = pages > 1 ? `swipe: more ${p + 1}/${pages} | dbl-tap: back` : 'hold: speak | tap: quick reply | dbl-tap: back'
  return [header, ...body, hint].join('\n')
}
