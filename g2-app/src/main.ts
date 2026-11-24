import {
  waitForEvenAppBridge,
  TextContainerProperty,
  CreateStartUpPageContainer,
  TextContainerUpgrade,
} from '@evenrealities/even_hub_sdk'
import { fetchInbox, reportUiState, SERVER_URL } from './api'
import { classifyGesture } from './gestures'
import { initialNav, reduce, render, type Nav } from './nav'
import type { Item } from './screens'
import { mountUi, setStatus, setTranscript } from './ui'

// Day 2: the shared inbox. Polls the VoiceLens server, shows voice notes
// (already transcribed) and texts, and lets you open and page through them.
// Replies (hold to speak) arrive on Day 3.

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

async function draw() {
  const content = online ? render(nav, items) : `VoiceLens\n\nCan't reach the VoiceLens server\n${SERVER_URL}\n\nStart it: server/run.py`
  void reportUiState(SERVER_URL, nav)
  if (content === shown) return
  shown = content
  setTranscript(content, '')
  await bridge.textContainerUpgrade(new TextContainerUpgrade({ containerID: 1, containerName: 'main', content }))
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
  const gesture = classifyGesture(event)
  if (gesture === null) return
  if (gesture === 'exit') { unsubscribe(); return }
  nav = reduce(nav, gesture, items)
  if (nav.screen === 'exit') {
    // The system shows its own confirmation dialog.
    bridge.shutDownPageContainer(1)
    nav = { ...nav, screen: 'inbox' }
    return
  }
  void draw()
})

await poll()
const timer = window.setInterval(() => void poll(), POLL_MS)
window.addEventListener('beforeunload', () => { window.clearInterval(timer); unsubscribe() })
