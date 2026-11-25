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

describe('reply API client', () => {
  it('joins mic chunks, sends them as base64 and returns the draft', async () => {
    const { prepareReply, toBase64 } = await import('./api')
    const fake = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ draft_id: 'd1', text: 'On my way', format: 'voice', chat_name: 'Mom' }) })
    const chunks = [new Uint8Array([1, 2]), new Uint8Array([3])]
    const r = await prepareReply('http://x', 10, chunks, fake as unknown as typeof fetch)
    expect(r).toEqual({ ok: true, draft: { draftId: 'd1', text: 'On my way', format: 'voice', chatName: 'Mom' } })
    const body = JSON.parse(fake.mock.calls[0][1].body)
    expect(body).toEqual({ item_id: 10, audio_b64: toBase64(new Uint8Array([1, 2, 3])) })
    expect(toBase64(new Uint8Array([1, 2, 3]))).toBe('AQID')
  })

  it('turns a server error into a short message for the glasses', async () => {
    const { prepareReply } = await import('./api')
    const fake = vi.fn().mockResolvedValue({ ok: false, json: async () => ({ detail: "didn't catch any speech, try again" }) })
    expect(await prepareReply('http://x', 10, [new Uint8Array([1])], fake as unknown as typeof fetch))
      .toEqual({ ok: false, message: "didn't catch any speech, try again" })
  })

  it('reports an empty recording without calling the server', async () => {
    const { prepareReply } = await import('./api')
    const fake = vi.fn()
    expect((await prepareReply('http://x', 10, [], fake as unknown as typeof fetch)).ok).toBe(false)
    expect(fake).not.toHaveBeenCalled()
  })

  it('sends and cancels drafts', async () => {
    const { sendReply, cancelReply } = await import('./api')
    const fake = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ sent: true }) })
    expect(await sendReply('http://x', 'd1', 'text', fake as unknown as typeof fetch)).toBe(true)
    expect(JSON.parse(fake.mock.calls[0][1].body)).toEqual({ draft_id: 'd1', format: 'text' })
    await cancelReply('http://x', 'd1', fake as unknown as typeof fetch)
    expect(fake.mock.calls[1][0]).toBe('http://x/reply/cancel')
  })
})

describe('reportUiState for reply screens', () => {
  it('reports recording and confirm screens, but not the exit request', async () => {
    const { reportUiState } = await import('./api')
    const fake = vi.fn().mockResolvedValue({ ok: true })
    await reportUiState('http://x', { screen: 'recording', selectedId: 1, page: 0 }, fake as unknown as typeof fetch)
    await reportUiState('http://x', { screen: 'exit', selectedId: 1, page: 0 }, fake as unknown as typeof fetch)
    expect(fake).toHaveBeenCalledTimes(1)
    expect(JSON.parse(fake.mock.calls[0][1].body).screen).toBe('recording')
  })
})

describe('reportUiState with a reply in progress', () => {
  it('includes the reply format, countdown and text', async () => {
    const { reportUiState } = await import('./api')
    const fake = vi.fn().mockResolvedValue({ ok: true })
    await reportUiState('http://x', { screen: 'confirm', selectedId: 1, page: 0, reply: { draftId: 'd', text: 'On my way', format: 'voice', chatName: 'Mom', countdown: 4 } }, fake as unknown as typeof fetch)
    expect(JSON.parse(fake.mock.calls[0][1].body)).toEqual({ screen: 'confirm', selected_id: 1, page: 0, reply_format: 'voice', countdown: 4, reply_text: 'On my way' })
  })
})

describe('quick reply client', () => {
  it('fetches quick replies', async () => {
    const { fetchQuickReplies } = await import('./api')
    const fake = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ items: [{ id: 'q1', label: 'On my way', duration: null, has_voice: false }] }) })
    expect(await fetchQuickReplies('http://x', fake as unknown as typeof fetch)).toEqual([{ id: 'q1', label: 'On my way', duration: null, has_voice: false }])
    expect(fake.mock.calls[0][0]).toBe('http://x/quick-replies')
  })

  it('returns null when the server is down', async () => {
    const { fetchQuickReplies } = await import('./api')
    expect(await fetchQuickReplies('http://x', vi.fn().mockRejectedValue(new TypeError('x')) as unknown as typeof fetch)).toBeNull()
  })

  it('asks for a quick-reply draft and maps voice availability', async () => {
    const { prepareQuick } = await import('./api')
    const fake = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ draft_id: 'd9', text: 'On my way', format: 'voice', chat_name: 'Mom', voice_available: true }) })
    expect(await prepareQuick('http://x', 10, 'q5', fake as unknown as typeof fetch)).toEqual({
      ok: true, draft: { draftId: 'd9', text: 'On my way', format: 'voice', chatName: 'Mom', voiceAvailable: true, quick: true },
    })
    expect(JSON.parse(fake.mock.calls[0][1].body)).toEqual({ item_id: 10, quick_id: 'q5' })
  })
})

describe('brief feature clients', () => {
  it('approves an AI draft as a text draft', async () => {
    const { prepareDraftText } = await import('./api')
    const fake = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ draft_id: 'd2', text: 'Yes, on it', format: 'text', chat_name: 'Rahul', voice_available: false }) })
    const r = await prepareDraftText('http://x', 10, 'Yes, on it', fake as unknown as typeof fetch)
    expect(r).toEqual({ ok: true, draft: { draftId: 'd2', text: 'Yes, on it', format: 'text', chatName: 'Rahul', voiceAvailable: false } })
    expect(fake.mock.calls[0][0]).toBe('http://x/reply/text')
  })

  it('sends a voice command and marks the draft as a new message', async () => {
    const { prepareCommand } = await import('./api')
    const fake = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ draft_id: 'd3', text: 'reached', format: 'text', chat_name: 'Mom', voice_available: true }) })
    const r = await prepareCommand('http://x', [new Uint8Array([1, 2])], fake as unknown as typeof fetch)
    expect(r).toMatchObject({ ok: true, draft: { chatName: 'Mom', command: true } })
    expect(fake.mock.calls[0][0]).toBe('http://x/command/prepare')
  })

  it('fetches digest lines, or explains the problem', async () => {
    const { fetchDigest } = await import('./api')
    const ok = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ lines: ['BTC 100k'] }) })
    expect(await fetchDigest('http://x', ok as unknown as typeof fetch)).toEqual(['BTC 100k'])
    const off = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ lines: [], error: 'Add ANTHROPIC_API_KEY' }) })
    expect(await fetchDigest('http://x', off as unknown as typeof fetch)).toEqual(['Add ANTHROPIC_API_KEY'])
  })
})
