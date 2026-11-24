# VoiceLens: G2 glasses app

The part of VoiceLens that runs on the glasses (a web app inside the Even Realities app, built with the Even Hub SDK). It shows the inbox, records your reply with the G2 microphone and handles gestures. All the heavy work happens in [`../server`](../server).

| File | What |
| --- | --- |
| `src/gestures.ts` | Raw G2 events → tap, double-tap, swipe up/down, hold, release |
| `src/screens.ts` | Inbox and message screens (48 × 10 plain ASCII, fits 576×288) |
| `src/nav.ts` | The UI as a pure state machine: inbox, message, recording, preview, sent |
| `src/api.ts` | Talks to the VoiceLens server (inbox, replies, UI state) |
| `src/main.ts` | Side effects: microphone on/off, upload, 5 s countdown, send |

```bash
npm install
npm test          # 53 tests
npm run dev       # http://localhost:5173
npm run simulate  # Even Hub simulator (uses your computer's microphone as the G2 mic)
```

Started from the official [`asr` template](https://github.com/even-realities/evenhub-templates) (MIT). `src/asr/stt.ts` is the template's unused stub.
