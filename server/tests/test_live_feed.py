"""Live transcription feed: keeps the newest entries and summarises speed."""

from voicelens.live_feed import add_entry, summarize


def entry(i, duration=5.0, transcribe=2.0, download=0.5, total=4.0):
    return {"id": i, "duration": duration, "download_s": download,
            "transcribe_s": transcribe, "total_s": total, "text": f"note {i}"}


def test_newest_entry_goes_first():
    feed = add_entry([entry(1)], entry(2))
    assert [e["id"] for e in feed] == [2, 1]


def test_feed_keeps_only_the_limit():
    feed = []
    for i in range(30):
        feed = add_entry(feed, entry(i), limit=20)
    assert len(feed) == 20
    assert feed[0]["id"] == 29


def test_speed_factor_is_processing_time_over_audio_length():
    feed = add_entry([], entry(1, duration=10.0, transcribe=2.0, download=0.5))
    assert feed[0]["speed_factor"] == 0.25  # (2.0 + 0.5) / 10


def test_summary_reports_average_fastest_and_slowest():
    feed = []
    for i, t in enumerate([1.0, 2.0, 3.0]):
        feed = add_entry(feed, entry(i, transcribe=t, total=t + 1))
    s = summarize(feed)
    assert s["count"] == 3
    assert s["avg_transcribe_s"] == 2.0
    assert s["fastest_s"] == 1.0
    assert s["slowest_s"] == 3.0
    assert s["avg_total_s"] == 3.0


def test_failed_entries_are_listed_but_not_counted_in_speed():
    feed = add_entry([entry(1, transcribe=2.0)], {"id": 2, "duration": 3.0, "error": "boom"})
    s = summarize(feed)
    assert s["count"] == 1
    assert s["errors"] == 1


def test_empty_feed_summary():
    assert summarize([])["count"] == 0
