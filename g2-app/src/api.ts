import type { Item } from './screens'

export async function fetchInbox(_base: string, _fetchFn: typeof fetch = fetch): Promise<Item[] | null> {
  throw new Error('not implemented')
}
