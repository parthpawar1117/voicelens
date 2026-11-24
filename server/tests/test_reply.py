"""Replies: format rule, audio conversion, and the prepare/send flow."""

import subprocess

import imageio_ffmpeg
import numpy as np
import pytest

from voicelens.reply import default_format, pcm_to_ogg_opus, toggle_format


def test_reply_matches_what_they_sent():
    assert default_format("voice") == "voice"
    assert default_format("text") == "text"


def test_swipe_switches_between_voice_and_text():
    assert toggle_format("voice") == "text"
    assert toggle_format("text") == "voice"


def test_unknown_kind_is_rejected():
    with pytest.raises(ValueError):
        default_format("sticker")


def test_glasses_pcm_becomes_a_telegram_voice_file(tmp_path):
    # 1 s of a 440 Hz tone as 16 kHz mono s16le, the G2 microphone format.
    t = np.arange(16000) / 16000
    pcm = (np.sin(2 * np.pi * 440 * t) * 8000).astype("<i2").tobytes()
    out = pcm_to_ogg_opus(pcm, tmp_path / "reply.ogg")
    assert out.exists() and out.stat().st_size > 500
    probe = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(out)],
        capture_output=True, text=True,
    ).stderr
    assert "opus" in probe and "ogg" in probe
    assert "Duration: 00:00:01" in probe


def test_empty_recording_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        pcm_to_ogg_opus(b"", tmp_path / "x.ogg")
