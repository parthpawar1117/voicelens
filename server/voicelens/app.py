"""FastAPI app the G2 plugin talks to."""

from __future__ import annotations

import base64
import binascii
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from voicelens.inbox import Inbox
from voicelens.quick_replies import QuickReplyStore
from voicelens.reply import DraftNotFound, NotAllowed, ReplyService, any_audio_to_pcm, pcm_to_ogg_opus


class UiState(BaseModel):
    screen: Literal["inbox", "message", "recording", "thinking", "confirm", "sending", "sent", "error"] | None = None
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


# The G2 plugin runs in a WebView; its fetch() needs CORS headers.
# Tightened to the real origin before packaging.
DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


def create_app(inbox: Inbox, replies: ReplyService | None = None,
               quick: QuickReplyStore | None = None, stt=None) -> FastAPI:
    app = FastAPI(title="VoiceLens")
    app.state.inbox = inbox
    app.state.replies = replies
    app.state.quick = quick
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
