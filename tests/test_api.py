"""HTTP API surface via Flask's test client."""
import pytest

from server.app import create_app


@pytest.fixture()
def client():
    app = create_app()
    app.testing = True
    return app.test_client()


def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.get_json()["ok"] is True


def test_settings_mask_and_validation(client):
    res = client.get("/api/settings")
    body = res.get_json()
    assert "ai" in body and body["ai"]["api_key"] == ""

    bad = client.put("/api/settings", json={"ai": {"provider": "nope"}})
    assert bad.status_code == 400

    ok = client.put("/api/settings", json={"ai": {"enabled": True, "model": "m"}})
    assert ok.status_code == 200


def test_ai_test_endpoint_offline(client):
    res = client.post("/api/ai/test", json={"ai": {"enabled": True, "model": "m", "base_url": "http://127.0.0.1:1/v1"}})
    body = res.get_json()
    assert body["ok"] is False


def test_packs_endpoints(client):
    res = client.get("/api/packs")
    ids = [p["id"] for p in res.get_json()["packs"]]
    assert "living_shore" in ids
    res = client.post("/api/packs/detail", json={"pack_id": "living_shore"})
    assert res.status_code == 200
    assert res.get_json()["pack"]["id"] == "living_shore"


def test_unknown_endpoint_is_json(client):
    res = client.get("/api/nope")
    assert res.status_code == 404
    assert "error" in res.get_json()


def test_client_shell_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert b"Which Portal on the Beam" in res.data


def test_full_campaign_http_lifecycle(client):
    res = client.post("/api/campaigns", json={
        "name": "HTTP Voyage", "pack_id": "living_shore",
        "character": {"name": "Net Traveler", "archetype": "warden", "specialty": "fight"},
    })
    assert res.status_code == 200
    cid = res.get_json()["campaign_id"]

    res = client.get(f"/api/campaigns/{cid}")
    assert res.get_json()["character"]["name"] == "Net Traveler"

    res = client.post(f"/api/campaigns/{cid}/action", json={"text": "I scan the shoreline."})
    assert res.status_code == 200
    assert res.get_json()["meta"]["ai_used"] is False  # AI disabled by default

    res = client.post(f"/api/campaigns/{cid}/travel", json={"location_id": "tavern"})
    assert res.status_code == 200

    res = client.post(f"/api/campaigns/{cid}/travel", json={"location_id": "nowhere"})
    assert res.status_code == 400

    res = client.post(f"/api/campaigns/{cid}/journal", json={"text": "A note."})
    assert res.status_code == 200

    res = client.get(f"/api/campaigns/{cid}/search?q=note")
    assert res.status_code == 200

    res = client.get(f"/api/campaigns/{cid}/transcript?limit=10")
    roles = [t["role"] for t in res.get_json()["transcript"]]
    assert "player" in roles and "gm" in roles

    res = client.post(f"/api/campaigns/{cid}/qr", json={"payload": "SM:CMD:INVENTORY"})
    assert res.get_json()["ok"] is True

    res = client.get(f"/api/campaigns/{cid}/export")
    assert res.status_code == 200
    data = res.get_json()

    res = client.post("/api/import", json=data)
    assert res.status_code == 200
    cid2 = res.get_json()["campaign_id"]

    res = client.delete(f"/api/campaigns/{cid2}")
    assert res.status_code == 200
    res = client.get(f"/api/campaigns/{cid2}")
    assert res.status_code == 404


def test_backup_roundtrip(client):
    res = client.post("/api/backup")
    assert res.status_code == 200
    bid = res.get_json()["id"]
    res = client.get("/api/backups")
    assert any(b["id"] == bid for b in res.get_json()["backups"])
    res = client.post(f"/api/backups/{bid}/restore")
    assert res.status_code == 200


def test_bad_campaign_404(client):
    res = client.get("/api/campaigns/cmp_missing")
    assert res.status_code == 404
