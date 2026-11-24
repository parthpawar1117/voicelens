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

describe('reportUiState', () => {
  it('posts the current screen so the dev dashboard can follow the glasses', async () => {
    const { reportUiState } = await import('./api')
    const fake = vi.fn().mockResolvedValue({ ok: true })
    await reportUiState('http://x', { screen: 'message', selectedId: 7, page: 1 }, fake as unknown as typeof fetch)
    const [url, init] = fake.mock.calls[0]
    expect(url).toBe('http://x/ui-state')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ screen: 'message', selected_id: 7, page: 1 })
  })

  it('never throws when the server is down', async () => {
    const { reportUiState } = await import('./api')
    const fake = vi.fn().mockRejectedValue(new TypeError('offline'))
    await expect(reportUiState('http://x', { screen: 'inbox', selectedId: null, page: 0 }, fake as unknown as typeof fetch)).resolves.toBeUndefined()
  })
})
