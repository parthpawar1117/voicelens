import {
  waitForEvenAppBridge,
  AudioInputSource,
  TextContainerProperty,
  CreateStartUpPageContainer,
  TextContainerUpgrade,
} from '@evenrealities/even_hub_sdk'
import { cancelReply, fetchInbox, prepareReply, reportUiState, sendReply, SERVER_URL } from './api'
import { classifyGesture, type Gesture } from './gestures'
import { initialNav, reduce, render, type AppEvent, type Nav } from './nav'
import type { Item } from './screens'
import { mountUi, setStatus, setTranscript } from './ui'

// Inbox + replies. nav.ts decides what happens; this file performs the side
// effects when the screen changes: microphone, upload, countdown, send.
// In the simulator the "G2 microphone" is your computer's microphone.

const POLL_MS = 1500

mountUi()
const bridge = await waitForEvenAppBridge()

const screen = new TextContainerProperty({
  xPosition: 0,
  yPosition: 0,
  width: 576,
  height: 288,
  borderWidth: 0,
  borderColor: 5,
  paddingLength: 8,
  containerID: 1,
  containerName: 'main',
  content: 'VoiceLens\n\nConnecting...',
  isEventCapture: 1,
})
const created = await bridge.createStartUpPageContainer(
  new CreateStartUpPageContainer({ containerTotalNum: 1, textObject: [screen] }),
)
if (created !== 0) setStatus('error', `createStartUpPageContainer failed: ${created}`)

let items: Item[] = []
let nav: Nav = initialNav(items)
let shown = ''
let online = false
let chunks: Uint8Array[] = []
let ticker: number | null = null

async function draw() {
  void reportUiState(SERVER_URL, nav)
  const content = online ? render(nav, items) : `VoiceLens\n\nCan't reach the VoiceLens server\n${SERVER_URL}\n\nStart it: server/run.py`
  if (content === shown) return
  shown = content
  setTranscript(content, '')
  await bridge.textContainerUpgrade(new TextContainerUpgrade({ containerID: 1, containerName: 'main', content }))
}

function stopTicker() {
  if (ticker !== null) { window.clearInterval(ticker); ticker = null }
}

// Run the side effects that belong to a screen change.
async function onTransition(prev: Nav, next: Nav) {
  if (prev.screen === next.screen) return

  if (next.screen === 'recording') {
    chunks = []
    await bridge.audioControl(true, AudioInputSource.Glasses)
  }
  if (prev.screen === 'recording') {
    await bridge.audioControl(false)
  }
  if (prev.screen === 'recording' && next.screen === 'thinking' && next.selectedId !== null) {
    const result = await prepareReply(SERVER_URL, next.selectedId, chunks)
    chunks = []
    dispatch(result.ok ? { type: 'draft', draft: result.draft } : { type: 'error', message: result.message })
  }
  if (next.screen === 'confirm') {
    stopTicker()
    ticker = window.setInterval(() => dispatch({ type: 'tick' }), 1000)
  }
  if (prev.screen === 'confirm') stopTicker()
  if (prev.screen === 'confirm' && next.screen === 'message' && prev.reply) {
    void cancelReply(SERVER_URL, prev.reply.draftId) // double tap during the countdown
  }
  if (next.screen === 'sending' && next.reply) {
    const ok = await sendReply(SERVER_URL, next.reply.draftId, next.reply.format)
    dispatch(ok ? { type: 'sent' } : { type: 'error', message: 'Sending failed. Nothing was sent.' })
  }
  if (next.screen === 'sent') {
    window.setTimeout(() => dispatch({ type: 'done' }), 2000)
  }
}

function dispatch(input: Gesture | AppEvent) {
  const prev = nav
  nav = reduce(nav, input, items)
  if (nav.screen === 'exit') {
    bridge.shutDownPageContainer(1) // the system shows its own confirmation dialog
    nav = { ...nav, screen: 'inbox' }
  }
  void draw()
  void onTransition(prev, nav)
}

async function poll() {
  const latest = await fetchInbox(SERVER_URL)
  online = latest !== null
  setStatus(online ? 'listening' : 'error', online ? `Connected · ${latest!.length} messages` : `Server offline: ${SERVER_URL}`)
  if (latest) {
    const wasEmpty = items.length === 0
    items = latest
    if (wasEmpty && nav.selectedId === null) nav = initialNav(items)
  }
  await draw()
}

const unsubscribe = bridge.onEvenHubEvent(event => {
  const pcm = event.audioEvent?.audioPcm
  if (pcm) {
    if (nav.screen === 'recording') chunks.push(new Uint8Array(pcm))
    return
  }
  const gesture = classifyGesture(event)
  if (gesture === null) return
  if (gesture === 'exit') { void bridge.audioControl(false); unsubscribe(); return }
  dispatch(gesture)
})

await poll()
const timer = window.setInterval(() => void poll(), POLL_MS)
window.addEventListener('beforeunload', () => { window.clearInterval(timer); stopTicker(); unsubscribe() })
