"""Seeded portal generation: determinism, structure, persistence."""
import pytest

from server import gen, gm, legacy


def test_seed_normalization():
    assert gen.normalize_seed("  Clockwork   OCEAN ") == "clockwork ocean"
    assert gen.normalize_seed("") == ""
    with pytest.raises(ValueError):
        gen.generate_world("   ")


def test_generation_is_deterministic():
    a = gen.generate_world("The Last Lighthouse")
    b = gen.generate_world("the last lighthouse")
    assert a["seed_hash"] == b["seed_hash"]
    assert a["name"] == b["name"]
    assert [l["id"] for l in a["locations"]] == [l["id"] for l in b["locations"]]
    assert a["adventures"][0]["scenes"] == b["adventures"][0]["scenes"]


def test_different_seeds_differ():
    a = gen.generate_world("Clockwork Ocean")
    b = gen.generate_world("Forgotten Kingdom")
    assert a["seed_hash"] != b["seed_hash"]
    assert a["name"] != b["name"]


def test_world_identity_is_complete():
    w = gen.generate_world("Saturday Night")
    assert w["name"] and w["archetype_label"] and w["weather"]
    assert len(w["locations"]) == 3
    assert len(w["npcs"]) == 2
    assert len(w["mysteries"]) == 2
    assert w["items"] and w["items"][0]["kind"] == "relic"
    adv = w["adventures"][0]
    assert adv["entry"] in adv["scenes"]
    assert set(adv["endings"]) >= {"world_kept", "world_owed", "world_refused"}
    # every choice target resolves
    for scene in adv["scenes"].values():
        for choice in scene.get("choices", []):
            for branch in (choice.get("on_pass"), choice.get("on_fail")):
                if branch and branch.get("goto"):
                    assert branch["goto"] in adv["scenes"]
    # the entry location starts the scenario
    assert w["locations"][0]["adventure"] == adv["id"]
    # relics are valid engine items
    relic = w["items"][0]
    assert relic["id"] and relic["name"]


def test_generator_version_pin():
    w = gen.generate_world("A City Without Shadows")
    assert w["gen_version"] == gen.GEN_VERSION
    assert gen.world_id("A City Without Shadows") == f"wld_{w['seed_hash'][:10]}"


def test_world_store_and_reuse(campaign):
    w1 = legacy.generate_and_store(campaign, "Clockwork Ocean")
    assert w1["existing"] is False
    w2 = legacy.generate_and_store(campaign, "  clockwork   ocean ")
    assert w2["existing"] is True
    assert w2["id"] == w1["id"]
    assert len(legacy.list_worlds(campaign)) == 1


def test_world_location_resolution_and_travel(campaign):
    w = legacy.generate_and_store(campaign, "The Last Lighthouse")
    entry = w["identity"]["entry_location"]
    pack = __import__("server.worldpacks", fromlist=["load_pack"]).load_pack("living_shore")
    loc, world = gm._resolve_location(campaign, pack, entry)
    assert loc and world and world["id"] == w["id"]
    gm.travel(campaign, entry)
    view = gm.campaign_view(campaign)
    assert view["world"]["name"] == w["identity"]["name"]
    assert view["scene"]["beat"] == "sig_arrival"
    # returning to the shore clears the world context
    gm.travel(campaign, "tidegate")
    view = gm.campaign_view(campaign)
    assert view["world"] is None


def test_signature_scenario_completes(campaign):
    w = legacy.generate_and_store(campaign, "Forgotten Kingdom")
    gm.travel(campaign, w["identity"]["entry_location"])
    gm.choose(campaign, "approach")
    view = gm.campaign_view(campaign)
    assert view["scene"]["beat"] == "sig_engage"
    res = gm.choose(campaign, "refuse")
    assert res["ending"] == "world_refused"
    view = gm.campaign_view(campaign)
    assert "world_refused" in view["endings_seen"]
    assert any(q["id"].startswith("sig_") for q in view["quests"])
    # the refusal echo offer exists at profile level
    echoes = legacy.list_echoes()
    assert any(e["kind"] == "achievement" and e["title"] == "Honest Refusal" for e in echoes)
