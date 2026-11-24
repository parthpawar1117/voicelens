"""FastAPI app the G2 plugin talks to."""

from __future__ import annotations

import base64
import binascii
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from voicelens.inbox import Inbox
from voicelens.reply import DraftNotFound, NotAllowed, ReplyService


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


# The G2 plugin runs in a WebView; its fetch() needs CORS headers.
# Tightened to the real origin before packaging.
DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


def create_app(inbox: Inbox, replies: ReplyService | None = None) -> FastAPI:
    app = FastAPI(title="VoiceLens")
    app.state.inbox = inbox
    app.state.replies = replies
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
        return {"draft_id": draft.id, "format": draft.format, "text": draft.text, "chat_name": draft.chat_name}

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
