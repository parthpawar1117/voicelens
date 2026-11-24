"""FastAPI app the G2 plugin talks to."""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from typing import Literal

from pydantic import BaseModel

from voicelens.inbox import Inbox


class UiState(BaseModel):
    screen: Literal["inbox", "message"] | None = None
    selected_id: int | None = None
    page: int = 0

# The G2 plugin runs in a WebView; its fetch() needs CORS headers.
# Tightened to the real origin before packaging.
DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


def create_app(inbox: Inbox) -> FastAPI:
    app = FastAPI(title="VoiceLens")
    app.state.inbox = inbox
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

    return app


app = create_app(Inbox())
