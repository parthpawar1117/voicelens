import type { Item } from './screens'

// The VoiceLens server (server/run.py). Override with VITE_SERVER_URL.
export const SERVER_URL: string =
  (import.meta.env?.VITE_SERVER_URL as string | undefined) ?? 'http://127.0.0.1:8787'

/** Tell the server what the glasses show (used by the dev dashboard). Never throws. */
export async function reportUiState(
  base: string,
  nav: { screen: string; selectedId: number | null; page: number },
  fetchFn: typeof fetch = fetch,
): Promise<void> {
  if (nav.screen !== 'inbox' && nav.screen !== 'message') return
  try {
    await fetchFn(`${base}/ui-state`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ screen: nav.screen, selected_id: nav.selectedId, page: nav.page }),
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
