from fastapi.testclient import TestClient

from voicelens.app import app


def test_health_reports_ok():
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_demo_bot_token_is_optional_and_read_from_env(monkeypatch, tmp_path):
    from voicelens import config
    monkeypatch.setattr(config, "SERVER_DIR", tmp_path)
    monkeypatch.setenv("TELEGRAM_API_ID", "1")
    monkeypatch.setenv("TELEGRAM_API_HASH", "abc")
    monkeypatch.delenv("TELEGRAM_DEMO_BOT_TOKEN", raising=False)
    assert config.load_settings().demo_bot_token is None
    monkeypatch.setenv("TELEGRAM_DEMO_BOT_TOKEN", "123:XYZ")
    assert config.load_settings().demo_bot_token == "123:XYZ"
