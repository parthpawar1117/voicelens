"""Live transcription feed: newest-first list of results plus speed summary.

speed_factor = (download + transcription time) / audio length.
Below 1.0 means the text is ready faster than the audio would take to play.
"""

from __future__ import annotations

FEED_LIMIT = 20


def add_entry(feed: list[dict], entry: dict, limit: int = FEED_LIMIT) -> list[dict]:
    entry = dict(entry)
    duration = entry.get("duration") or 0
    if "error" not in entry and duration > 0:
        processing = entry.get("download_s", 0) + entry.get("transcribe_s", 0)
        entry["speed_factor"] = round(processing / duration, 2)
    return [entry, *feed][:limit]


def summarize(feed: list[dict]) -> dict:
    ok = [e for e in feed if "error" not in e]
    errors = len(feed) - len(ok)
    if not ok:
        return {"count": 0, "errors": errors}
    times = [e["transcribe_s"] for e in ok]
    totals = [e["total_s"] for e in ok if e.get("total_s") is not None]
    factors = [e["speed_factor"] for e in ok if "speed_factor" in e]
    return {
        "count": len(ok),
        "errors": errors,
        "avg_transcribe_s": round(sum(times) / len(times), 2),
        "fastest_s": round(min(times), 2),
        "slowest_s": round(max(times), 2),
        "avg_total_s": round(sum(totals) / len(totals), 2) if totals else None,
        "avg_speed_factor": round(sum(factors) / len(factors), 2) if factors else None,
    }
