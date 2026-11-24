import { OsEventTypeList } from '@evenrealities/even_hub_sdk'

export type Gesture =
  | 'tap'
  | 'double_tap'
  | 'swipe_up'
  | 'swipe_down'
  | 'long_press'
  | 'long_press_release'
  | 'exit'

interface Envelope {
  eventType?: OsEventTypeList
}

interface HubEventLike {
  sysEvent?: Envelope
  textEvent?: Envelope
  listEvent?: Envelope
}

const GESTURES: Partial<Record<OsEventTypeList, Gesture>> = {
  [OsEventTypeList.CLICK_EVENT]: 'tap',
  [OsEventTypeList.DOUBLE_CLICK_EVENT]: 'double_tap',
  [OsEventTypeList.SCROLL_TOP_EVENT]: 'swipe_up',
  [OsEventTypeList.SCROLL_BOTTOM_EVENT]: 'swipe_down',
  [OsEventTypeList.LONG_PRESS_EVENT]: 'long_press',
  [OsEventTypeList.LONG_PRESS_RELEASE_EVENT]: 'long_press_release',
  [OsEventTypeList.SYSTEM_EXIT_EVENT]: 'exit',
  [OsEventTypeList.ABNORMAL_EXIT_EVENT]: 'exit',
}

// CLICK_EVENT is 0 and protobuf omits zero values, so a tap arrives as an
// envelope with no eventType. The default is applied only when an envelope
// exists; audio-only frames carry no envelope and must never become taps.
function typeOf(envelope?: Envelope): OsEventTypeList | null {
  if (!envelope) return null
  return envelope.eventType ?? OsEventTypeList.CLICK_EVENT
}

export function classifyGesture(event: unknown): Gesture | null {
  const e = (event ?? {}) as HubEventLike
  const type = typeOf(e.sysEvent) ?? typeOf(e.textEvent) ?? typeOf(e.listEvent)
  if (type === null) return null
  return GESTURES[type] ?? null
}

export function helloScreen(last: Gesture | null, count: number): string {
  const header = 'VoiceLens\nVoice notes, readable.\n\n'
  if (last === null) return `${header}Try a gesture: tap, swipe,\ndouble-tap to exit.`
  return `${header}Last gesture: ${last} (${count})`
}
