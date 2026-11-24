import { describe, expect, it, vi } from 'vitest'
import { fetchInbox } from './api'

describe('fetchInbox', () => {
  it('returns the items from the server', async () => {
    const fake = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ count: 1, items: [{ id: 1 }] }) })
    expect(await fetchInbox('http://x', fake as unknown as typeof fetch)).toEqual([{ id: 1 }])
    expect(fake).toHaveBeenCalledWith('http://x/inbox', expect.anything())
  })

  it('returns null when the server is unreachable, so the screen can say so', async () => {
    const fake = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))
    expect(await fetchInbox('http://x', fake as unknown as typeof fetch)).toBeNull()
  })

  it('returns null on an error status', async () => {
    const fake = vi.fn().mockResolvedValue({ ok: false, json: async () => ({}) })
    expect(await fetchInbox('http://x', fake as unknown as typeof fetch)).toBeNull()
  })
})
