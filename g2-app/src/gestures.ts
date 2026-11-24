import { OsEventTypeList } from '@evenrealities/even_hub_sdk'

export type Gesture =
  | 'tap'
  | 'double_tap'
  | 'swipe_up'
  | 'swipe_down'
  | 'long_press'
  | 'long_press_release'
  | 'exit'

export function classifyGesture(_event: unknown): Gesture | null {
  throw new Error('not implemented')
}

export function helloScreen(_last: Gesture | null, _count: number): string {
  throw new Error('not implemented')
}
