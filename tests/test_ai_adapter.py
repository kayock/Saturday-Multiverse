"""AI adapter: JSON extraction, config validation, real endpoint calls."""
import pytest

from server import ai


def test_extract_json_plain():
    data = ai.extract_json('{"narration": "hello", "check": null}')
    assert data["narration"] == "hello"


def test_extract_json_fenced_and_chatty():
    text = """Sure! Here's the object:
```json
{"narration": "waves", "nested": {"a": "b {c}"}}
```
Hope that helps!"""
    data = ai.extract_json(text)
    assert data["narration"] == "waves"
    assert data["nested"]["a"] == "b {c}"


def test_extract_json_quotes_inside_strings():
    data = ai.extract_json('{"narration": "she said \\"no\\" and left"}')
    assert "no" in data["narration"]


def test_extract_json_garbage():
    assert ai.extract_json("no json at all") is None
    assert ai.extract_json("") is None
    assert ai.extract_json("{broken") is None


def test_config_validation():
    with pytest.raises(ValueError):
        ai.set_ai_config({"provider": "not-a-thing"})
    with pytest.raises(ValueError):
        ai.set_ai_config({"base_url": "ftp://bad"})
    cfg = ai.set_ai_config({"temperature": 99, "max_tokens": 999999})
    assert cfg["temperature"] <= 2.0
    assert cfg["max_tokens"] <= 4000


def test_masked_config_hides_key():
    ai.set_ai_config({"api_key": "super-secret", "enabled": True})
    masked = ai.masked_ai_config()
    assert masked["api_key"] == ""
    assert masked["has_key"] is True
    assert "super-secret" not in str(masked)


def test_chat_requires_config():
    ai.set_ai_config({"enabled": False})
    with pytest.raises(ai.AiError) as exc:
        ai.chat([{"role": "user", "content": "hi"}])
    assert exc.value.kind == "config"


def test_chat_connection_error():
    ai.set_ai_config({"enabled": True, "model": "m",
                      "base_url": "http://127.0.0.1:1/v1"})  # nothing listens there
    with pytest.raises(ai.AiError) as exc:
        ai.chat([{"role": "user", "content": "hi"}])
    assert exc.value.kind == "connection"


def test_chat_against_mock_server(mock_gm_url):
    ai.set_ai_config({"enabled": True, "model": "mock-gm-1", "base_url": mock_gm_url})
    content, meta = ai.chat([{"role": "user", "content": "I listen to the doors"}])
    assert "narration" in content or "{" in content
    assert meta["model"] == "mock-gm-1"
    data = ai.extract_json(content)
    assert isinstance(data.get("narration"), str) and data["narration"]


def test_full_turn_with_mock_gm(mock_gm_url, campaign):
    """End-to-end: a real HTTP model call drives one game turn."""
    from server import db, gm

    ai.set_ai_config({"enabled": True, "model": "mock-gm-1", "base_url": mock_gm_url})
    res = gm.run_turn(campaign, "I ask the shore about the kelp lanterns.")
    assert res["meta"]["ai_used"] is True
    assert res["narration"]
    # the mock requested a notice check: the app rolled it, not the model
    assert res["dice"] is not None
    assert res["dice"]["dice"]
    assert res["dice"]["outcome"] in rules_bands()
    # the mock asked to give dried_kelp: validated against the catalog and applied
    inv = {i["item_id"] for i in gm.get_inventory(campaign)}
    assert "dried_kelp" in inv
    # hidden note must be stored hidden, never shown in visible facts
    view = gm.campaign_view(campaign)
    assert not any("tenth lantern" in f for f in view["facts"])
    hidden = db.query(
        "SELECT text FROM facts WHERE campaign_id=? AND scope='hidden'", (campaign,)
    )
    assert any("tenth lantern" in r["text"] for r in hidden)
    # transcript recorded both sides
    roles = [r["role"] for r in db.query(
        "SELECT role FROM transcript WHERE campaign_id=? ORDER BY rowid", (campaign,)
    )]
    assert roles[-2:] == ["player", "gm"]


def rules_bands():
    from server import rules
    return rules.BANDS
