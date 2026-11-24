# VoiceLens

Read Telegram voice notes on Even Realities G2 glasses, and answer them with a real voice note.

G2 has no speaker, so a voice note on the glasses is a dead end. VoiceLens shows it as text,
transcribed by Telegram itself (`messages.transcribeAudio`), and lets you reply by holding the
temple and speaking. No third-party AI ever reads your messages.

Built for the **Heads Up: Even Realities Hackathon** (DoraHacks, Nov 23–29, 2026) —
Track 01 Messaging & News + Best Telegram integration.

> Status: work in progress.

## How it works

```
Voice note arrives -> Telegram transcribes it -> VoiceLens server -> Even app (phone) -> G2 display
G2 microphone -> VoiceLens server -> OGG Opus voice note -> sent from your Telegram account
```

## Repository layout

| Path | What |
| --- | --- |
| `g2-app/` | Glasses app: Vite + TypeScript + Even Hub SDK |
| `server/` | Backend: Python, FastAPI + Telethon |

## Setup

Setup steps will be added as the build progresses.

## Privacy and Telegram rules

- Only chats you pick are read.
- Nothing is sent without your tap, and every send has a 3-second undo.
- Voice notes are never marked as "listened" (Telegram API Terms 1.4): we only show a transcript.
- No message content is sent to any third-party AI service (Telegram API Terms 1.5).
- Secrets live in `server/.env` (gitignored). The glasses app never contains API keys.

## Prior work (what existed before Nov 23, 2026)

All project code in this repository was written from Nov 24, 2026, during the hackathon.
Pre-existing work used:

- [even-realities/evenhub-templates](https://github.com/even-realities/evenhub-templates) (MIT) — the `asr` template was the starting point for `g2-app/`.
- Open-source libraries listed in `g2-app/package.json` and `server/requirements.txt`
  (Even Hub SDK, Vite, FastAPI, Telethon, imageio-ffmpeg, pytest).
- Built with AI coding assistance (Claude Code).
