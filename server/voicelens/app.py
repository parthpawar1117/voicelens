"""FastAPI app the G2 plugin talks to."""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from voicelens.inbox import Inbox

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

    @app.get("/inbox/{item_id}")
    def get_item(item_id: int) -> dict:
        item = app.state.inbox.get(item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Message not in the inbox")
        return item.to_dict()

    return app


app = create_app(Inbox())
