import {
  waitForEvenAppBridge,
  TextContainerProperty,
  CreateStartUpPageContainer,
  TextContainerUpgrade,
} from '@evenrealities/even_hub_sdk'
import { classifyGesture, helloScreen, type Gesture } from './gestures'
import { mountUi, setStatus, setTranscript } from './ui'

// Day-1 milestone: prove the round trip glasses -> app -> glasses.
// One text container on screen; every gesture is classified and echoed back.
// The microphone stays off until the voice-reply feature lands.

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
  content: helloScreen(null, 0),
  isEventCapture: 1,
})

const created = await bridge.createStartUpPageContainer(
  new CreateStartUpPageContainer({ containerTotalNum: 1, textObject: [screen] }),
)
if (created !== 0) {
  setStatus('error', `createStartUpPageContainer failed: ${created}`)
} else {
  setStatus('listening', 'Connected · try a gesture on the glasses')
}

let gestureCount = 0

async function render(last: Gesture) {
  const content = helloScreen(last, gestureCount)
  setTranscript(content, '')
  await bridge.textContainerUpgrade(
    new TextContainerUpgrade({ containerID: 1, containerName: 'main', content }),
  )
}

const unsubscribe = bridge.onEvenHubEvent(event => {
  const gesture = classifyGesture(event)
  if (gesture === null) return

  console.log('[VoiceLens] gesture', gesture)

  if (gesture === 'double_tap') {
    // Always leave an exit: the system shows its own confirmation dialog.
    bridge.shutDownPageContainer(1)
    return
  }
  if (gesture === 'exit') {
    unsubscribe()
    return
  }

  gestureCount += 1
  void render(gesture)
})

window.addEventListener('beforeunload', () => unsubscribe())
