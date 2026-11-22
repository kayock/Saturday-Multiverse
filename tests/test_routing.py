"""Game Master routing: host choice, busy/offline fallback, forge escalation."""
import urllib.error

import pytest

from server import ai, routing


def _tags(names, sizes=None):
    sizes = sizes or {}
    return {"models": [{"name": n, "size": sizes.get(n, 1_400_000_000)} for n in names]}


def _ps(names, sizes=None):
    sizes = sizes or {}
    return {"models": [{"name": n, "size": sizes.get(n, 1_400_000_000)} for n in names]}


@pytest.fixture()
def fleet(monkeypatch):
    """Both hosts up, both lightweight models installed, nothing else loaded."""
    state = {
        "station_tags": _tags(["saturday-gm-gamemaster:latest", "saturday-gm-gemmasutra:latest"]),
        "station_ps": _ps([]),
        "portable_tags": _tags(["saturday-gm-gamemaster:latest", "saturday-gm-gemmasutra:latest",
                                "qwen3.5:4b"], {"qwen3.5:4b": 3_400_000_000}),
        "portable_ps": _ps([]),
        "extra": None,
    }

    def fake(url, timeout=1.2):
        if url.startswith("http://station:11434/api/tags"):
            return state["station_tags"]
        if url.startswith("http://station:11434/api/ps"):
            return state["station_ps"]
        if url.startswith("http://portable:11434/api/tags"):
            return state["portable_tags"]
        if url.startswith("http://portable:11434/api/ps"):
            return state["portable_ps"]
        if state["extra"] and url == state["extra"]["url"]:
            return state["extra"]["body"]
        if url.startswith("http://portable"):
            raise urllib.error.URLError("portable down")
        raise urllib.error.URLError("no such host " + url)

    monkeypatch.setattr(routing, "fetch_json", fake)
    routing.set_routing({
        "mode": "auto",
        "escalation": "on",
        "primary_model": "saturday-gm-gamemaster",
        "fallback_model": "saturday-gm-gemmasutra",
        "station_url": "http://station:11434/v1",
        "portable_url": "http://portable:11434/v1",
        "advanced_model": "",
        "advanced_base_url": "",
    })
    return state


def test_manual_mode_does_not_touch_the_network(monkeypatch):
    def boom(url, timeout=1.2):
        raise AssertionError("network probe during manual mode: " + url)

    monkeypatch.setattr(routing, "fetch_json", boom)
    routing.set_routing({"mode": "manual"})
    assert routing.choose([{"role": "user", "content": "I listen"}]) is None


def test_auto_prefers_free_portable(fleet):
    choice = routing.choose([{"role": "user", "content": "I walk the tideline"}])
    assert choice["host"] == "portable"
    assert choice["model"] == "saturday-gm-gamemaster"
    assert choice["tier"] == "light"


def test_busy_portable_falls_back_to_station(fleet):
    fleet["portable_ps"] = _ps(["gemma4:12b"], {"gemma4:12b": 8_000_000_000})
    routing._cache["data"] = None
    choice = routing.choose([{"role": "user", "content": "I walk"}])
    assert choice["host"] == "station"
    assert "busy" in choice["note"]


def test_offline_portable_falls_back_to_station(fleet):
    fleet["portable_tags"] = None  # fetch raises for portable tag urls that don't match
    # Force the portable branch to raise: empty prefix match falls through to URLError
    # when tags is None the startswith still matches and returns None, which would crash.
    # Point portable at a host the fake treats as down.
    routing.set_routing({"portable_url": "http://portable-down:11434/v1"})
    choice = routing.choose([{"role": "user", "content": "I walk"}])
    assert choice["host"] == "station"
    assert "offline" in choice["note"]


def test_missing_primary_uses_fallback_model(fleet):
    fleet["station_tags"] = _tags(["saturday-gm-gemmasutra:latest"])
    fleet["portable_tags"] = _tags(["saturday-gm-gemmasutra:latest"])
    routing._cache["data"] = None
    choice = routing.choose([{"role": "user", "content": "I walk"}])
    assert choice["model"] == "saturday-gm-gemmasutra"
    assert "primary unavailable" in choice["note"]


def test_gameplay_never_uses_a_large_model(fleet):
    fleet["portable_ps"] = _ps(["qwen3.5:4b"], {"qwen3.5:4b": 3_400_000_000})
    routing.set_routing({
        "advanced_model": "qwen3.5:4b",
        "advanced_base_url": "http://portable:11434/v1",
    })
    choice = routing.choose([{"role": "user", "content": "I speak to the keeper"}])
    assert choice["tier"] == "light"
    assert choice["host"] == "station"  # portable is busy while the large model is loaded
    assert choice["model"] == "saturday-gm-gamemaster"


def test_forge_uses_advanced_only_when_already_loaded(fleet):
    forge = [{"role": "system", "content": "You are the Campaign Forge's analyst."},
             {"role": "user", "content": "SOURCE EXCERPT"}]
    routing.set_routing({
        "advanced_model": "qwen3.5:4b",
        "advanced_base_url": "http://portable:11434/v1",
    })
    cold = routing.choose(forge)
    assert cold["tier"] == "light"  # pinned, but not loaded — do not start it

    fleet["portable_ps"] = _ps(["qwen3.5:4b"], {"qwen3.5:4b": 3_400_000_000})
    routing._cache["data"] = None
    hot = routing.choose(forge)
    assert hot["tier"] == "advanced"
    assert hot["model"] == "qwen3.5:4b"
    assert hot["host"] == "portable"


def test_escalation_off_keeps_forge_on_the_lightweight_model(fleet):
    fleet["portable_ps"] = _ps(["qwen3.5:4b"], {"qwen3.5:4b": 3_400_000_000})
    routing.set_routing({
        "escalation": "off",
        "advanced_model": "qwen3.5:4b",
        "advanced_base_url": "http://portable:11434/v1",
    })
    choice = routing.choose([{"role": "system", "content": "You are the Campaign Forge's world-builder."}])
    assert choice["tier"] == "light"


def test_shared_endpoint_is_manual_and_already_running_only(fleet, monkeypatch):
    monkeypatch.setenv("SATURDAY_GM_DISCOVER", "http://shared:11435/v1")
    fleet["extra"] = {"url": "http://shared:11435/v1/models",
                       "body": {"data": [{"id": "kayock-local"}]}}
    routing.set_routing({
        "advanced_model": "kayock-local",
        "advanced_base_url": "http://shared:11435/v1",
    })
    play = routing.choose([{"role": "user", "content": "I walk"}])
    assert play["tier"] == "light"
    forge = routing.choose([{"role": "system", "content": "You are the Campaign Forge's analyst of record."}])
    assert forge["tier"] == "advanced"
    assert forge["model"] == "kayock-local"


def test_invalid_mode_is_rejected():
    with pytest.raises(ValueError):
        routing.set_routing({"mode": "yolo"})


def test_extract_json_strips_thinking_and_rejects_unclosed_thinking():
    data = ai.extract_json('<think>{"narration": "secret plan"}</think>\n{"narration": "the lamp gutters"}')
    assert data["narration"] == "the lamp gutters"
    assert ai.extract_json('<think>still thinking {"narration": "nope"}') is None


def test_prefer_station_order(fleet):
    routing.set_routing({"mode": "prefer_station"})
    choice = routing.choose([{"role": "user", "content": "I walk"}])
    assert choice["host"] == "station"
