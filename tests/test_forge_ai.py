"""Campaign Forge model selection stays independent of the Game Master.

Online providers are mocked. These tests never call a real hosted API.
"""
import base64

import pytest

from server import ai, db, forge, forge_ai


def _doc(client):
    res = client.post("/api/library/import", json={
        "filename": "lamp.md",
        "title": "The Short Lamp",
        "data_b64": base64.b64encode(b"# Lamp\n\nThe keeper counts the tides.\n").decode(),
        "license": "Private",
        "private": True,
    })
    assert res.status_code == 200, res.get_json()
    return res.get_json()


def test_locality_of_common_addresses():
    assert forge_ai.locality("http://127.0.0.1:11434/v1") == "local"
    assert forge_ai.locality("http://10.0.0.202:11434/v1") == "local"
    assert forge_ai.locality("http://192.168.1.20:11434/v1") == "local"
    assert forge_ai.locality("http://8.8.8.8/v1") == "online"
    assert forge_ai.locality("http://mock/v1") == "unknown"
    assert forge_ai.locality("http://nas.local:11434/v1") == "local"


def test_auto_uses_configured_local_model_without_changing_it(monkeypatch):
    monkeypatch.setattr(forge_ai, "_loaded_advanced", lambda: None)
    ai.set_ai_config({"enabled": True, "model": "saturday-gm-gamemaster",
                      "base_url": "http://127.0.0.1:11434/v1", "api_key": "game-key"})
    forge_ai.set_config({"selection": "auto_local"})
    cfg = forge_ai.resolve()
    assert cfg["model"] == "saturday-gm-gamemaster"
    assert cfg["_direct"] is True
    assert cfg["api_key"] == ""
    assert ai.get_ai_config()["model"] == "saturday-gm-gamemaster"
    assert ai.get_ai_config()["api_key"] == "game-key"


def test_auto_refuses_an_online_game_master(monkeypatch):
    ai.set_ai_config({"enabled": True, "model": "gpt-test",
                      "base_url": "https://api.openai.com/v1"})
    forge_ai.set_config({"selection": "auto_local"})
    called = {"n": 0}
    monkeypatch.setattr(ai, "chat", lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    with pytest.raises(forge_ai.ForgeAiError) as exc:
        forge_ai.resolve()
    assert "Nothing was sent" in str(exc.value)
    assert called["n"] == 0


def test_online_requires_approval_and_hides_the_key(monkeypatch):
    ai.set_ai_config({"enabled": True, "model": "game-master",
                      "base_url": "http://127.0.0.1:11434/v1"})
    forge_ai.set_config({
        "selection": "online",
        "provider_name": "Hosted compatible",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "example/model",
        "api_key": "secret-key-value",
    })
    called = {"n": 0}
    monkeypatch.setattr(ai, "chat", lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    with pytest.raises(forge_ai.ForgeAiError) as exc:
        forge_ai.resolve()
    assert "Nothing was sent" in str(exc.value)
    assert "secret-key-value" not in str(exc.value)
    assert called["n"] == 0
    masked = forge_ai.masked()
    assert masked["api_key"] == "" and masked["has_key"] is True
    approved = forge_ai.resolve(transmit_approved=True)
    assert approved["model"] == "example/model"
    assert approved["_tier"] == "online"
    assert approved["_direct"] is True
    assert ai.get_ai_config()["model"] == "game-master"


def test_failed_local_choice_does_not_become_online(monkeypatch):
    from server import routing
    ai.set_ai_config({"enabled": True, "model": "game-master",
                      "base_url": "http://127.0.0.1:11434/v1"})
    forge_ai.set_config({
        "selection": "local",
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "big-novel",
        "api_key": "should-not-be-used",
    })
    monkeypatch.setattr(routing, "snapshot", lambda force=False: {
        "station": {"ok": True, "models": [{"name": "big-novel", "size": 8_000_000_000}],
                    "loaded": []},
        "portable": {"ok": False, "models": [], "loaded": []},
        "extra": [],
    })
    with pytest.raises(forge_ai.ForgeAiError) as exc:
        forge_ai.resolve()
    assert "not running" in str(exc.value)
    assert "Nothing was sent" in str(exc.value)


def test_prices_are_estimates_only_when_the_operator_supplied_them():
    forge_ai.set_config({
        "selection": "online",
        "base_url": "https://example.invalid/v1",
        "model": "example",
        "price_input_per_million": None,
        "price_output_per_million": None,
    })
    bare = forge_ai.preview(8000)
    assert bare["cost_estimate"] is None
    assert bare["pricing"] == "unavailable"
    forge_ai.set_config({"price_input_per_million": 1.5, "price_output_per_million": 3})
    priced = forge_ai.preview(8000)
    assert priced["cost_estimate"] is not None
    assert priced["pricing"] == "operator"
    assert "Not a provider quote" in priced["note"]


def test_window_never_shrinks():
    assert forge_ai.window_chars({}) == 9000
    assert forge_ai.window_chars({"_context": 4096}) == 9000
    wider = forge_ai.window_chars({"_context": 32768})
    assert 9000 < wider <= 24000


def test_job_pins_the_forge_model_and_refuses_unapproved_online(client, monkeypatch):
    monkeypatch.setattr(forge_ai, "_loaded_advanced", lambda: None)
    doc = _doc(client)
    ai.set_ai_config({"enabled": True, "model": "game-master",
                      "base_url": "http://mock/v1"})
    forge_ai.set_config({
        "selection": "online",
        "provider_name": "Hosted",
        "base_url": "https://example.invalid/v1",
        "model": "hosted-model",
        "api_key": "secret-key-value",
    })
    with pytest.raises(forge.JobError) as exc:
        forge.create_job(doc["id"], "faithful", "short")
    assert "Nothing was sent" in str(exc.value)
    assert db.query("SELECT id FROM forge_jobs WHERE doc_id=?", (doc["id"],)) == []
    forge_ai.set_config({"selection": "auto_local"})
    job = forge.create_job(doc["id"], "expanded", "short")
    assert job["mode"] == "expanded"
    pin = db.get_json_setting("forge_job_ai", {})[job["id"]]
    assert pin["model"] == "game-master"
    assert "api_key" not in pin
    assert ai.get_ai_config()["model"] == "game-master"
    saved = client.get("/api/settings").get_json()
    assert saved["ai"]["model"] == "game-master"
    assert saved["forge_ai"]["api_key"] == ""
    forge.cancel_job(job["id"])


def test_retry_failed_window_does_not_restart_the_book(client, monkeypatch):
    doc = _doc(client)
    ai.set_ai_config({"enabled": True, "model": "game-master",
                      "base_url": "http://mock/v1"})
    forge_ai.set_config({"selection": "auto_local"})
    job = forge.create_job(doc["id"], "faithful", "short")
    db.execute(
        "UPDATE forge_jobs SET profile_json=?, coverage_json=? WHERE id=?",
        ('{"characters":[{"name":"Keeper","role":"keeper"}]}',
         '{"windows_planned":2,"windows_failed":1,"failed_windows":[{"window":1,"reason":"contract missed"}],'
         '"window_chars":9000,"extraction_successful":false}',
         job["id"]),
    )
    seen = {"n": 0}

    def fake_chat(messages, cfg=None):
        seen["n"] += 1
        assert cfg.get("_direct") is True
        assert "SOURCE EXCERPT" in messages[-1]["content"]
        return ('{"characters":[{"name":"Keeper","role":"keeper","goals":"count"}]}',
                {"model": "game-master"})

    monkeypatch.setattr(ai, "chat", fake_chat)
    out = forge.retry_failed_windows(job["id"])
    assert seen["n"] == 1
    assert out["coverage"]["failed_windows"] == []
    assert out["coverage"]["extraction_successful"] is True
    assert any(c["name"] == "Keeper" for c in out["profile"]["characters"])
    forge.cancel_job(job["id"])


def test_settings_save_does_not_replace_the_game_master(client):
    ai.set_ai_config({"enabled": True, "model": "game-master",
                      "base_url": "http://127.0.0.1:11434/v1"})
    res = client.put("/api/settings", json={"forge_ai": {
        "selection": "online",
        "provider_name": "Hosted",
        "base_url": "https://example.invalid/v1",
        "model": "hosted-model",
        "api_key": "secret-key-value",
    }})
    assert res.status_code == 200
    body = res.get_json()
    assert body["ai"]["model"] == "game-master"
    assert body["forge_ai"]["model"] == "hosted-model"
    assert body["forge_ai"]["api_key"] == ""
    assert "secret-key-value" not in res.get_data(as_text=True)
