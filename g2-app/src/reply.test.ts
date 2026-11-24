import { describe, expect, it } from 'vitest'
import { reduce, render, type Nav } from './nav'
import { LINE_CHARS, SCREEN_LINES, type Item } from './screens'

const items: Item[] = [
  { id: 10, chat_name: 'Mom', kind: 'text', text: 'Where are you?', duration: null, received_at: '21:00', source: null },
]
const onMessage: Nav = { screen: 'message', selectedId: 10, page: 0 }
const draft = { draftId: 'd1', text: 'Ten minutes, almost home.', format: 'text' as const, chatName: 'Mom' }

const fits = (screen: string) => {
  const lines = screen.split('\n')
  expect(lines.length).toBeLessThanOrEqual(SCREEN_LINES)
  for (const l of lines) expect(l.length).toBeLessThanOrEqual(LINE_CHARS)
}

describe('starting and stopping a recording', () => {
  it('holding on a message starts recording', () => {
    expect(reduce(onMessage, 'long_press', items).screen).toBe('recording')
  })

  it('tap on a message opens quick replies; tap while recording still stops it', () => {
    expect(reduce(onMessage, 'tap', items).screen).toBe('quick')
    const rec = reduce(onMessage, 'long_press', items)
    expect(reduce(rec, 'tap', items).screen).toBe('thinking')
  })

  it('releasing the hold stops recording and waits for the preview', () => {
    const rec = reduce(onMessage, 'long_press', items)
    expect(reduce(rec, 'long_press_release', items).screen).toBe('thinking')
  })

  it('swipes are ignored while recording (the simulator sends stray scroll events)', () => {
    const rec = reduce(onMessage, 'long_press', items)
    expect(reduce(rec, 'swipe_up', items)).toEqual(rec)
    expect(reduce(rec, 'swipe_down', items)).toEqual(rec)
  })

  it('double tap while recording cancels back to the message', () => {
    const rec = reduce(onMessage, 'long_press', items)
    expect(reduce(rec, 'double_tap', items)).toMatchObject({ screen: 'message', selectedId: 10 })
  })

  it('cannot reply from the inbox list', () => {
    expect(reduce({ screen: 'inbox', selectedId: 10, page: 0 }, 'long_press', items).screen).toBe('inbox')
  })
})

describe('preview and countdown', () => {
  const thinking: Nav = { screen: 'thinking', selectedId: 10, page: 0 }

  it('a ready draft shows the confirm screen with a 5 second countdown', () => {
    const s = reduce(thinking, { type: 'draft', draft }, items)
    expect(s.screen).toBe('confirm')
    expect(s.reply).toMatchObject({ countdown: 5, format: 'text', text: 'Ten minutes, almost home.' })
  })

  it('each tick counts down; at zero it moves to sending', () => {
    let s = reduce(thinking, { type: 'draft', draft }, items)
    s = reduce(s, { type: 'tick' }, items)
    expect(s.reply?.countdown).toBe(4)
    for (let i = 0; i < 3; i++) s = reduce(s, { type: 'tick' }, items)
    expect(s.screen).toBe('confirm') // still 1 s left
    s = reduce(s, { type: 'tick' }, items)
    expect(s.screen).toBe('sending')
  })

  it('swipe up always chooses text, swipe down always chooses voice', () => {
    let s = reduce(thinking, { type: 'draft', draft: { ...draft, format: 'voice' } }, items)
    s = reduce(s, 'swipe_up', items)
    expect(s.reply?.format).toBe('text')
    s = reduce(s, 'swipe_up', items) // a double-read swipe can't flip it back
    expect(s.reply?.format).toBe('text')
    s = reduce(s, 'swipe_down', items)
    expect(s.reply?.format).toBe('voice')
    expect(reduce(s, 'swipe_down', items).reply?.format).toBe('voice')
    expect(s.screen).toBe('confirm') // choosing never sends
  })

  it('changing the format restarts the countdown; choosing the same one does not', () => {
    let s = reduce(thinking, { type: 'draft', draft }, items) // text
    s = reduce(s, { type: 'tick' }, items)
    expect(reduce(s, 'swipe_up', items).reply?.countdown).toBe(4) // already text
    expect(reduce(s, 'swipe_down', items).reply?.countdown).toBe(5) // changed to voice
  })

  it('a tap during the preview changes nothing and never sends early', () => {
    const s = reduce(thinking, { type: 'draft', draft }, items)
    expect(reduce(s, 'tap', items)).toEqual(s)
  })

  it('double tap cancels and returns to the message', () => {
    const s = reduce(thinking, { type: 'draft', draft }, items)
    const back = reduce(s, 'double_tap', items)
    expect(back).toMatchObject({ screen: 'message', selectedId: 10 })
    expect(back.reply).toBeUndefined() // the draft is dropped
  })

  it('after sending it shows sent, then the inbox', () => {
    const sending: Nav = { ...reduce(thinking, { type: 'draft', draft }, items), screen: 'sending' }
    const sent = reduce(sending, { type: 'sent' }, items)
    expect(sent.screen).toBe('sent')
    expect(reduce(sent, { type: 'done' }, items)).toMatchObject({ screen: 'inbox', selectedId: 10 })
  })

  it('an error shows a message and goes back to the message on any gesture', () => {
    const err = reduce(thinking, { type: 'error', message: "Didn't catch any speech" }, items)
    expect(err.screen).toBe('error')
    expect(render(err, items)).toContain("Didn't catch any speech")
    expect(reduce(err, 'tap', items).screen).toBe('message')
  })
})

describe('reply screens', () => {
  it('recording, thinking, confirm and sent screens fit the display', () => {
    const rec: Nav = { screen: 'recording', selectedId: 10, page: 0 }
    expect(render(rec, items)).toContain('Recording')
    const conf = reduce({ screen: 'thinking', selectedId: 10, page: 0 }, { type: 'draft', draft }, items)
    const text = render(conf, items)
    expect(text).toContain('You said:')
    expect(text).toContain('Ten minutes, almost home.')
    expect(text).toContain('Sending text in 5')
    expect(text).toContain('> ^ TEXT')
    expect(text).toContain('v VOICE NOTE')
    for (const s of [rec, { ...rec, screen: 'thinking' as const }, conf, { ...conf, screen: 'sent' as const }]) fits(render(s, items))
  })
})
