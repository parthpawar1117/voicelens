"""FastAPI app the G2 plugin talks to."""

from __future__ import annotations

import base64
import binascii
import tempfile
import time
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from voicelens.inbox import Inbox
from voicelens.quick_replies import QuickReplyStore
from voicelens.reply import DraftNotFound, NotAllowed, ReplyService, any_audio_to_pcm, pcm_to_ogg_opus


class UiState(BaseModel):
    screen: Literal["inbox", "message", "quick", "digest", "recording", "thinking", "confirm", "sending", "sent", "error"] | None = None
    selected_id: int | None = None
    page: int = 0
    reply_format: Literal["voice", "text"] | None = None  # while a reply is previewed
    countdown: int | None = None
    reply_text: str | None = None


class PrepareReply(BaseModel):
    item_id: int
    audio_b64: str  # G2 mic audio: 16 kHz mono s16le, base64


class SendReply(BaseModel):
    draft_id: str
    format: Literal["voice", "text"]


class CancelReply(BaseModel):
    draft_id: str


class QuickReplyIn(BaseModel):
    label: str | None = None
    audio_b64: str | None = None  # any recording; becomes your voice clip


class SendQuick(BaseModel):
    item_id: int
    quick_id: str


class ApproveDraft(BaseModel):
    item_id: int
    text: str


class PickChat(BaseModel):
    chat_id: int
    picked: bool


class CommandIn(BaseModel):
    audio_b64: str  # G2 mic audio: 16 kHz mono s16le, base64


# The G2 plugin runs in a WebView; its fetch() needs CORS headers.
# Tightened to the real origin before packaging.
DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


DIGEST_TTL_S = 60


def create_app(inbox: Inbox, replies: ReplyService | None = None,
               quick: QuickReplyStore | None = None, stt=None, chats=None, writer=None) -> FastAPI:
    app = FastAPI(title="VoiceLens")
    app.state.inbox = inbox
    app.state.replies = replies
    app.state.quick = quick
    app.state.chats = chats
    app.state.writer = writer
    app.state.digest = (0.0, None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=DEV_ORIGINS,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/inbox")
    def list_inbox() -> dict:
        items = [x.to_dict() for x in app.state.inbox.items()]
        return {"count": len(items), "items": items}

    # What the glasses are showing, reported by the G2 app after each redraw.
    # Lets the dev dashboard follow the glasses and jump to a message safely.
    app.state.ui = UiState()

    @app.get("/ui-state")
    def get_ui_state() -> UiState:
        return app.state.ui

    @app.post("/ui-state")
    def set_ui_state(state: UiState) -> UiState:
        app.state.ui = state
        return state

    @app.get("/inbox/{item_id}")
    def get_item(item_id: int) -> dict:
        item = app.state.inbox.get(item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Message not in the inbox")
        return item.to_dict()

    def reply_service() -> ReplyService:
        if app.state.replies is None:
            raise HTTPException(status_code=503, detail="Replies need the Telegram server (server/run.py)")
        return app.state.replies

    @app.post("/reply/prepare")
    async def prepare_reply(body: PrepareReply) -> dict:
        svc = reply_service()
        try:
            pcm = base64.b64decode(body.audio_b64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=400, detail="Audio is not valid base64")
        try:
            draft = await svc.prepare(item_id=body.item_id, pcm=pcm)
        except DraftNotFound as err:
            raise HTTPException(status_code=404, detail=str(err))
        except NotAllowed as err:
            raise HTTPException(status_code=403, detail=str(err))
        except ValueError as err:
            raise HTTPException(status_code=422, detail=str(err))
        return draft_json(draft)

    def draft_json(draft) -> dict:
        return {"draft_id": draft.id, "format": draft.format, "text": draft.text,
                "chat_name": draft.chat_name, "voice_available": draft.voice_available}

    # ---- quick replies: saved once (text + your voice), sent silently ----

    def quick_store() -> QuickReplyStore:
        if app.state.quick is None:
            raise HTTPException(status_code=503, detail="Quick replies need the full server (server/run.py)")
        return app.state.quick

    @app.get("/quick-replies")
    def list_quick() -> dict:
        return {"items": [q.to_dict() for q in quick_store().list()]}

    @app.post("/quick-replies")
    async def add_quick(body: QuickReplyIn) -> dict:
        store = quick_store()
        label = (body.label or "").strip()
        if not label and not body.audio_b64:
            raise HTTPException(status_code=422, detail="Type the reply or record it")
        ogg = duration = None
        if body.audio_b64:
            try:
                audio = base64.b64decode(body.audio_b64, validate=True)
            except (binascii.Error, ValueError):
                raise HTTPException(status_code=400, detail="Audio is not valid base64")
            try:
                pcm = any_audio_to_pcm(audio)
            except Exception:
                raise HTTPException(status_code=400, detail="Couldn't read that recording")
            if len(pcm) < 3200:  # under 0.1 s
                raise HTTPException(status_code=422, detail="The recording is too short")
            duration = round(len(pcm) / 32000, 1)
            if not label and stt is not None:
                label = (await stt(pcm)).strip()
            if not label:
                raise HTTPException(status_code=422, detail="Couldn't hear any words. Type the reply text too")
            with tempfile.TemporaryDirectory() as tmp:
                ogg = pcm_to_ogg_opus(pcm, Path(tmp) / "clip.ogg").read_bytes()
        try:
            q = store.add(label, ogg=ogg, duration=duration)
        except ValueError as err:
            raise HTTPException(status_code=422, detail=str(err))
        return q.to_dict()

    @app.delete("/quick-replies/{qid}")
    def delete_quick(qid: str) -> dict:
        quick_store().delete(qid)
        return {"deleted": True}

    @app.post("/reply/quick")
    async def send_quick(body: SendQuick) -> dict:
        try:
            draft = await reply_service().prepare_quick(item_id=body.item_id, quick_id=body.quick_id)
        except DraftNotFound as err:
            raise HTTPException(status_code=404, detail=str(err))
        except NotAllowed as err:
            raise HTTPException(status_code=403, detail=str(err))
        return draft_json(draft)

    # ---- brief features: pick chats, digest, approve AI drafts, voice commands ----

    def chat_dir():
        if app.state.chats is None:
            raise HTTPException(status_code=503, detail="Chat list needs the Telegram server (server/run.py)")
        return app.state.chats

    @app.get("/chats")
    def list_chats() -> dict:
        return {"chats": chat_dir().listing()}

    @app.post("/chats/pick")
    def pick_chat(body: PickChat) -> dict:
        chat_dir().pick(body.chat_id, body.picked)
        return {"ok": True}

    @app.get("/digest")
    async def digest() -> dict:
        if app.state.writer is None:
            return {"lines": [], "error": "Add ANTHROPIC_API_KEY to server/.env for digests"}
        made_at, cached = app.state.digest
        if cached is not None and time.monotonic() - made_at < DIGEST_TTL_S:
            return cached
        by_chat: dict[str, list[str]] = {}
        for x in reversed(app.state.inbox.items()):  # oldest first
            if app.state.chats is None or app.state.chats.is_watched(x.chat_id):
                by_chat.setdefault(x.chat_name, []).append(x.text)
        result = {"lines": await app.state.writer.digest(by_chat)}
        app.state.digest = (time.monotonic(), result)
        return result

    @app.post("/reply/text")
    async def approve_draft(body: ApproveDraft) -> dict:
        try:
            draft = await reply_service().prepare_text(item_id=body.item_id, text=body.text)
        except DraftNotFound as err:
            raise HTTPException(status_code=404, detail=str(err))
        except NotAllowed as err:
            raise HTTPException(status_code=403, detail=str(err))
        except ValueError as err:
            raise HTTPException(status_code=422, detail=str(err))
        return draft_json(draft)

    @app.post("/command/prepare")
    async def command(body: CommandIn) -> dict:
        try:
            pcm = base64.b64decode(body.audio_b64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=400, detail="Audio is not valid base64")
        result = await reply_service().prepare_command(pcm=pcm, chats=chat_dir().known)
        if "error" in result:
            raise HTTPException(status_code=422, detail=result["error"])
        return draft_json(result["draft"])

    @app.post("/reply/send")
    async def send_reply(body: SendReply) -> dict:
        try:
            draft = await reply_service().send(body.draft_id, fmt=body.format)
        except DraftNotFound as err:
            raise HTTPException(status_code=404, detail=str(err))
        return {"sent": True, "format": draft.format, "chat_name": draft.chat_name}

    @app.post("/reply/cancel")
    def cancel_reply(body: CancelReply) -> dict:
        reply_service().cancel(body.draft_id)
        return {"cancelled": True}

    return app


app = create_app(Inbox())
