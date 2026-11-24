import { describe, expect, it } from 'vitest'
import { OsEventTypeList } from '@evenrealities/even_hub_sdk'
import { classifyGesture, helloScreen } from './gestures'

describe('classifyGesture', () => {
  it('treats a sysEvent with no eventType as a tap (protobuf drops 0)', () => {
    expect(classifyGesture({ sysEvent: {} })).toBe('tap')
  })

  it('reads double tap from sysEvent or textEvent', () => {
    expect(classifyGesture({ sysEvent: { eventType: OsEventTypeList.DOUBLE_CLICK_EVENT } })).toBe('double_tap')
    expect(classifyGesture({ textEvent: { eventType: OsEventTypeList.DOUBLE_CLICK_EVENT } })).toBe('double_tap')
  })

  it('maps scroll events to swipes', () => {
    expect(classifyGesture({ textEvent: { eventType: OsEventTypeList.SCROLL_TOP_EVENT } })).toBe('swipe_up')
    expect(classifyGesture({ textEvent: { eventType: OsEventTypeList.SCROLL_BOTTOM_EVENT } })).toBe('swipe_down')
  })

  it('maps long press and its release', () => {
    expect(classifyGesture({ sysEvent: { eventType: OsEventTypeList.LONG_PRESS_EVENT } })).toBe('long_press')
    expect(classifyGesture({ sysEvent: { eventType: OsEventTypeList.LONG_PRESS_RELEASE_EVENT } })).toBe('long_press_release')
  })

  it('maps exit events', () => {
    expect(classifyGesture({ sysEvent: { eventType: OsEventTypeList.SYSTEM_EXIT_EVENT } })).toBe('exit')
    expect(classifyGesture({ sysEvent: { eventType: OsEventTypeList.ABNORMAL_EXIT_EVENT } })).toBe('exit')
  })

  it('ignores audio-only frames so mic data never fires a tap', () => {
    expect(classifyGesture({ audioEvent: { audioPcm: new Uint8Array(4) } })).toBeNull()
  })
})

describe('helloScreen', () => {
  it('shows the app name and a tap prompt before any input', () => {
    const text = helloScreen(null, 0)
    expect(text).toContain('VoiceLens')
    expect(text).toContain('tap')
  })

  it('reports the last gesture and how many gestures were received', () => {
    expect(helloScreen('swipe_down', 3)).toContain('swipe_down (3)')
  })
})
