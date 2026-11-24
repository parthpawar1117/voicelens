"""FastAPI app the G2 plugin talks to. Telegram access is added feature by feature."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="VoiceLens")

# The G2 plugin runs in a WebView; its fetch() needs CORS headers.
# Tightened to the real origin before packaging.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
