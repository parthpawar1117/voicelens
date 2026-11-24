import type { ReplyDraft, ReplyFormat } from './nav'
import type { Item } from './screens'

// The VoiceLens server (server/run.py). Override with VITE_SERVER_URL.
export const SERVER_URL: string =
  (import.meta.env?.VITE_SERVER_URL as string | undefined) ?? 'http://127.0.0.1:8787'

export function toBase64(bytes: Uint8Array): string {
  let binary = ''
  const step = 0x8000 // avoid call-stack limits on long recordings
  for (let i = 0; i < bytes.length; i += step) binary += String.fromCharCode(...bytes.subarray(i, i + step))
  return btoa(binary)
}

function join(chunks: Uint8Array[]): Uint8Array {
  const out = new Uint8Array(chunks.reduce((n, c) => n + c.length, 0))
  let at = 0
  for (const c of chunks) { out.set(c, at); at += c.length }
  return out
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown }
    if (typeof body.detail === 'string') return body.detail
  } catch { /* fall through */ }
  return 'The server could not prepare your reply'
}

const post = (fetchFn: typeof fetch, url: string, body: unknown) =>
  fetchFn(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

export type PrepareResult = { ok: true; draft: ReplyDraft } | { ok: false; message: string }

/** Upload your recording; get back what Whisper heard, as a draft to confirm. */
export async function prepareReply(base: string, itemId: number, chunks: Uint8Array[], fetchFn: typeof fetch = fetch): Promise<PrepareResult> {
  const pcm = join(chunks)
  if (pcm.length === 0) return { ok: false, message: "No audio was recorded. Check the microphone and try again." }
  try {
    const res = await post(fetchFn, `${base}/reply/prepare`, { item_id: itemId, audio_b64: toBase64(pcm) })
    if (!res.ok) return { ok: false, message: await errorMessage(res) }
    const d = (await res.json()) as { draft_id: string; text: string; format: ReplyFormat; chat_name: string }
    return { ok: true, draft: { draftId: d.draft_id, text: d.text, format: d.format, chatName: d.chat_name } }
  } catch {
    return { ok: false, message: "Can't reach the VoiceLens server." }
  }
}

export async function sendReply(base: string, draftId: string, format: ReplyFormat, fetchFn: typeof fetch = fetch): Promise<boolean> {
  try {
    const res = await post(fetchFn, `${base}/reply/send`, { draft_id: draftId, format })
    return res.ok
  } catch {
    return false
  }
}

export async function cancelReply(base: string, draftId: string, fetchFn: typeof fetch = fetch): Promise<void> {
  try { await post(fetchFn, `${base}/reply/cancel`, { draft_id: draftId }) } catch { /* nothing to undo */ }
}

/** Tell the server what the glasses show (used by the dev dashboard). Never throws. */
export async function reportUiState(
  base: string,
  nav: { screen: string; selectedId: number | null; page: number; reply?: { format: ReplyFormat; countdown: number; text: string } },
  fetchFn: typeof fetch = fetch,
): Promise<void> {
  if (nav.screen === 'exit') return
  const body: Record<string, unknown> = { screen: nav.screen, selected_id: nav.selectedId, page: nav.page }
  if (nav.reply) Object.assign(body, { reply_format: nav.reply.format, countdown: nav.reply.countdown, reply_text: nav.reply.text })
  try {
    await fetchFn(`${base}/ui-state`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch {
    // The dashboard is a dev aid; the glasses must keep working without it.
  }
}

/** Newest-first inbox items, or null if the server can't be reached. */
export async function fetchInbox(base: string, fetchFn: typeof fetch = fetch): Promise<Item[] | null> {
  try {
    const res = await fetchFn(`${base}/inbox`, { cache: 'no-store' })
    if (!res.ok) return null
    const body = (await res.json()) as { items: Item[] }
    return body.items
  } catch {
    return null
  }
}
