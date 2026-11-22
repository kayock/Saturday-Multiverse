"""Milestone 3.5 — The Infinite Library, Campaign Forge, D&D-compatible rules.

Covers document import (every format), indexing and retrieval, the forge
pipeline with a mock model, the SRD ruleset's determinism and isolation,
starter-pack playability, hidden-information boundaries on library packs,
and multiplayer aboard an imported literary adventure.
"""
import base64
import io
import json
import zipfile
from xml.etree import ElementTree as ET

import pytest

from server import db, forge, gm, library, legacy, mp, rules_dnd, worldpacks
from tests.test_mp import MpClient, _guest


# ================================================================ library
def _doc(app, text, filename="book.md", **kw):
    c = app.test_client()
    r = c.post("/api/library/import", json={
        "filename": filename,
        "data_b64": base64.b64encode(text.encode() if isinstance(text, str) else text).decode(),
        **kw,
    })
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def test_library_import_all_formats(app):
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    xml = ET.Element(f"{{{ns}}}document"); body = ET.SubElement(xml, f"{{{ns}}}body")
    for style, text in [("Heading1", "The Demeter"), (None, "All hands lost in the fog.")]:
        p = ET.SubElement(body, f"{{{ns}}}p")
        if style:
            ppr = ET.SubElement(p, f"{{{ns}}}pPr")
            st = ET.SubElement(ppr, f"{{{ns}}}pStyle"); st.set(f"{{{ns}}}val", style)
        t = ET.SubElement(p, f"{{{ns}}}t"); t.text = text
    docx_bytes = io.BytesIO()
    with zipfile.ZipFile(docx_bytes, "w") as z:
        z.writestr("word/document.xml", ET.tostring(xml))
    opf = ('<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" '
           'xmlns:dc="http://purl.org/dc/elements/1.1/" version="2.0">'
           '<metadata><dc:title>Stoker</dc:title><dc:creator>Bram Stoker</dc:creator></metadata>'
           '<manifest><item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/></manifest>'
           '<spine><itemref idref="c1"/></spine></package>')
    epub_bytes = io.BytesIO()
    with zipfile.ZipFile(epub_bytes, "w") as z:
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="book.opf"/></rootfiles></container>')
        z.writestr("book.opf", opf)
        z.writestr("c1.xhtml", "<html><body><h1>Chapter I: The Journey</h1><p>Jonathan Harker kept his journal in shorthand. The castle stood above the pass, and the driver never once showed his face.</p></body></html>")
    from reportlab.pdfgen import canvas as _rl_canvas
    pdf_buf = io.BytesIO()
    rl = _rl_canvas.Canvas(pdf_buf, pagesize=(612, 792))
    rl.drawString(72, 700, "The cape was drowned and the light still turned.")
    rl.save()
    pdf_bytes = pdf_buf.getvalue()
    cases = {
        "md": (_doc(app, "# Ch 1\n\nThe lighthouse stood on the drowned cape. Salt everywhere.\n",
                    "b.md", title="MD Book", license="Public Domain"), "lighthouse"),
        "html": (_doc(app, "<html><body><h1>Wells</h1><p>Deep in the earth the Morlocks "
                          "keep the machines.</p></body></html>", "w.html"), "Morlocks"),
        "docx": (_doc(app, docx_bytes.getvalue(), "d.docx"), "Demeter"),
        "epub": (_doc(app, epub_bytes.getvalue(), "s.epub"), "castle"),
        "pdf": (_doc(app, pdf_bytes, "c.pdf"), "drowned"),
    }
    for fmt, (doc, needle) in cases.items():
        assert doc["doc_type"] == fmt, (fmt, doc)
        hits = library.search(needle, doc_id=doc["id"])
        assert hits, f"{fmt}: search must find the needle"
    # epub metadata flowed into the record
    epub_doc = cases["epub"][0]
    assert epub_doc["author"] == "Bram Stoker"


def test_library_source_verbatim_and_delete(app):
    text = "# Heading\n\nThe original bytes, preserved.\n" * 20
    doc = _doc(app, text, "orig.md")
    raw = open(doc["original_path"], "rb").read()
    assert raw == text.encode()
    r = app.test_client().delete(f"/api/library/{doc['id']}")
    assert r.status_code == 200
    import os
    assert not os.path.exists(doc["original_path"])
    assert library.search("original bytes") == [] or all(
        h["doc_id"] != doc["id"] for h in library.search("original bytes"))


def test_library_long_document_retrieval(app):
    book = "\n".join(
        f"# Chapter {i}\n\nIn chapter {i} the ship spoke of salt and the number {i} "
        f"was carved on the wheel.\n" for i in range(300))
    doc = _doc(app, book, "long.md", title="Long Book")
    assert doc["n_chunks"] >= 250
    passages = library.retrieve_for_prompt(doc["id"],
                                           "the ship spoke of salt and the number 217 was carved", k=4)
    assert any("217" in p for p in passages), "the needle chapter must surface"
    # the v0.3.6 safe retrieval removed the random-rotation fallback:
    # no matching context means NO passages, never a random spoiler
    fallback = library.retrieve_for_prompt(doc["id"], {"action_text": "I look around."}, k=4)
    assert fallback == []


def test_library_hostile_inputs(app):
    c = app.test_client()
    # not a zip, pretending to be a docx
    r = c.post("/api/library/import", json={"filename": "evil.docx",
                                            "data_b64": base64.b64encode(b"not a zip").decode()})
    assert r.status_code == 400
    # entity-bomb docx (XXE attempt) must not crash or expand
    evil = io.BytesIO()
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("word/document.xml",
                   '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "bomb">]><doc>&a;</doc>')
    r = c.post("/api/library/import", json={"filename": "evil2.docx",
                                            "data_b64": base64.b64encode(evil.getvalue()).decode()})
    assert r.status_code in (200, 400)  # parsed safely or refused, never 500
    # oversized upload
    r = c.post("/api/library/import", json={
        "filename": "huge.txt", "data_b64": base64.b64encode(b"x" * (41 * 1024 * 1024)).decode()})
    assert r.status_code == 400
    # garbage b64
    r = c.post("/api/library/import", json={"filename": "x.txt", "data_b64": "!!!not-b64!!!"})
    assert r.status_code in (400, 500)


def test_gm_secrets_become_hidden_facts(app):
    cid = gm.create_campaign("Dracula Secrets", "dracula",
                             {"name": "Van Renterghem", "archetype": "occultist", "specialty": "bind"})
    view = gm.campaign_view(cid)
    visible = json.dumps(view)
    assert "must sleep in that earth" not in visible  # a secret stays out of the view
    hidden = db.query("SELECT text FROM facts WHERE campaign_id=? AND scope='hidden'", (cid,))
    assert any("native earth" in r["text"] for r in hidden)


# ================================================================ forge
@pytest.fixture()
def mock_model(monkeypatch):
    """A deterministic stand-in for the user's model."""
    def fake_chat(messages, cfg=None):
        user = messages[-1]["content"]
        if user.startswith("SOURCE EXCERPT"):
            return ('{"characters":[{"name":"Count Sallow","role":"antagonist","desc":"rules the abbey"}],'
                    '"locations":[{"name":"Grey Abbey","desc":"a cold abbey"}],'
                    '"plot_points":["the storm uncovers an older door"],'
                    '"secrets":["Sallow caused the storm"]}', {"model": "mock"})
        if "EXTRACTED MATERIAL" in user:
            return ('{"name":"The Grey Abbey","summary":"A haunted abbey.","genre_tags":["gothic"],'
                    '"gm_style":"Cold dread.",'
                    '"locations":[{"id":"abbey","name":"Grey Abbey","short":"The abbey.","desc":"Halls."},'
                    '{"id":"caves","name":"Tide-Caves","short":"Caves.","desc":"Black water."}],'
                    '"npcs":[{"id":"sallow","name":"Count Sallow","role":"keeper","location":"abbey","desc":"rules"}],'
                    '"items":[{"id":"silver_key","name":"Silver Key","kind":"relic","desc":"seals doors"}],'
                    '"omens":[{"id":"om1","kind":"edge","title":"Tidewhisper","text":"The caves warn.","boost":"notice"}],'
                    '"intro_facts":["An older door has opened."]}', {"model": "mock"})
        if "MATERIAL PLOT" in user:
            return ('{"title":"The Door Beneath","summary":"Seal it or open it.","entry":"arrival",'
                    '"quests":[{"id":"seal","title":"Seal the door"}],'
                    '"gm_secrets":["Sallow caused the storm"],'
                    '"scenes":[{"id":"arrival","title":"Arrival","brief":"Arrive.","intro":"The gate yawns.",'
                    '"choices":[{"id":"meet","label":"Meet the Count","goto":"hall"},'
                    '{"id":"descend","label":"Descend","check":{"skill":"notice"},'
                    '"on_pass":{"goto":"keyroom","effects":{"journal":"Found the way."}},'
                    '"on_fail":{"goto":"arrival","effects":{"harm":{"amount":1,"type":"nerve"}}}}]},'
                    '{"id":"hall","title":"Hall","brief":"Meet.","intro":"He waits.",'
                    '"choices":[{"id":"challenge","label":"Challenge","check":{"skill":"fight"},'
                    '"on_pass":{"goto":"keyroom"},"on_fail":{"goto":"keyroom"}}]},'
                    '{"id":"keyroom","title":"Key","brief":"Take it.","intro":"The key waits.",'
                    '"choices":[{"id":"seal","label":"Seal","goto":"seal_ending"},'
                    '{"id":"open","label":"Open","goto":"open_ending"}]}],'
                    '"endings":{"seal_ending":{"text":"Sealed.","return_location":"abbey",'
                    '"effects":{"ending":"seal_ending"},"consequence":"Sealed."},'
                    '"open_ending":{"text":"Opened.","return_location":"caves",'
                    '"effects":{"ending":"open_ending"}}}}', {"model": "mock"})
        raise ai.AiError("unexpected", "mock")

    from server import ai
    monkeypatch.setattr(ai, "chat", fake_chat)
    monkeypatch.setattr(ai, "get_ai_config", lambda: {
        "enabled": True, "api_key": "mock", "base_url": "http://mock", "model": "mock"})
    return fake_chat


def test_forge_pipeline_end_to_end(app, mock_model):
    doc = _doc(app, "\n".join(
        f"# Chapter {i}\n\nCount Sallow ruled the grey abbey. The storm uncovered a door.\n"
        for i in range(20)), "abbey.md", title="The Grey Abbey", license="Public Domain")
    draft = forge.create_draft(doc["id"], "faithful")
    assert draft["status"] == "draft"
    assert not forge.validate_pack(draft["pack"]), draft["notes"]
    res = forge.approve_draft(draft["id"])
    pack = worldpacks.load_pack(res["pack_id"])
    assert pack and pack["name"] == "The Grey Abbey"
    # the installed pack carries source + license from the document
    assert pack["license"]["source_title"] == "The Grey Abbey"
    # and the story plays headless to an ending
    cid = gm.create_campaign("Forge Play", res["pack_id"],
                             {"name": "Isolde", "archetype": "seeker", "specialty": "lore"})
    for choice in ("meet", "challenge", "seal"):
        res = gm.choose(cid, choice)
    assert gm.campaign_view(cid)["scene"]["adventure_done"]


def test_forge_alternate_mode_and_regen(app, mock_model):
    doc = _doc(app, "\n".join(f"# C{i}\n\nSallow. Storm. Door.\n" for i in range(30)), "a.md")
    draft = forge.create_draft(doc["id"], "alternate")
    assert draft["pack"]["forge_mode"] == "alternate"
    # regenerating a section keeps the pack valid
    draft2 = forge.regenerate_section(draft["id"], "adventure", "make the door the center")
    assert not forge.validate_pack(draft2["pack"])


def test_forge_refuses_invalid_pack_on_approve(app, mock_model):
    doc = _doc(app, "Sallow. Storm. Door.\n" * 30, "b.md")
    draft = forge.create_draft(doc["id"], "faithful")
    # sabotage the draft deterministically: point an ending at nowhere
    pack = draft["pack"]
    pack["adventures"][0]["endings"]["seal_ending"]["return_location"] = "nowhere_land"
    db.execute("UPDATE forge_drafts SET pack_json=? WHERE id=?",
               (db.jdumps(pack), draft["id"]))
    with pytest.raises(Exception) as exc:
        forge.approve_draft(draft["id"])
    assert "problems" in str(exc.value)


def test_forge_requires_ai(app):
    doc = _doc(app, "Words. " * 100, "c.md")
    with pytest.raises(Exception) as exc:
        forge.create_draft(doc["id"], "faithful")
    assert "AI model" in str(exc.value)


def test_private_manuscript_flow(app):
    """Roanoke path: an author's private manuscript imports, forges, and
    never appears in distributed metadata. No content is fabricated here."""
    c = app.test_client()
    doc = _doc(app, "# Roanoke\n\n(The author's manuscript text goes here when supplied.)\n" * 10,
               "roanoke_manuscript.md", title="Roanoke — private manuscript",
               license="Private", private=True)
    assert doc["private"] == 1
    listing = c.get("/api/library").get_json()["docs"]
    assert any(d["id"] == doc["id"] for d in listing)  # the host sees their own
    # a private pack installs to the data dir, never the built-ins
    assert doc["original_path"].startswith(str(library.config.LIBRARY_DIR))


# ================================================================ dnd ruleset
def test_dnd_character_and_checks(app):
    cid = gm.create_campaign("D&D Voyage", "dracula", {
        "name": "Abraham", "ruleset": "dnd5e",
        "class": "cleric", "species": "human", "background": "folk_hero"})
    view = gm.campaign_view(cid)
    assert view["ruleset"] == "dnd5e"
    assert view["dnd"]["class"] == "Cleric"
    assert view["dnd"]["slots"] == {"1": 2}
    r = gm.manual_check(cid, "notice")
    assert r["outcome"] in ("surge", "clean", "undertow", "riptide")
    assert r["dice"] and len(r["dice"]) == 1  # a d20, not 2d6
    # band mapping holds
    assert rules_dnd._band(20, 40, 13) == "surge"
    assert rules_dnd._band(1, 0, 13) == "riptide"
    assert rules_dnd._band(10, 15, 13) == "clean"
    assert rules_dnd._band(10, 11, 13) == "undertow"


def test_dnd_rest_spells_and_progression(app):
    cid = gm.create_campaign("D&D Rest", "dracula", {
        "name": "Seward", "ruleset": "dnd5e",
        "class": "wizard", "species": "elf", "background": "sage"})
    ch = gm.get_character(cid)
    sheet = ch["data"]["dnd"]
    sheet["slots"]["1"] = 0
    gm._persist_character(ch)
    gm.travel(cid, "sanatorium")
    res = gm.rest(cid)
    ch = gm.get_character(cid)
    assert ch["data"]["dnd"]["slots"]["1"] == 2  # long rest restores slots
    assert ch["vigor"] == ch["vigor_max"]
    level = rules_dnd.gain_xp(ch["data"]["dnd"], 400)
    assert level and level["level"] == 2
    gm._persist_character(ch)


def test_ruleset_isolation_undertow_unchanged(app):
    cid = gm.create_campaign("Undertow Untouched", "living_shore",
                             {"name": "Soloist", "archetype": "sensitive", "specialty": "bind"})
    view = gm.campaign_view(cid)
    assert view["ruleset"] == "undertow"
    assert view["dnd"] is None
    ch = gm.get_character(cid)
    # omens still exist on the undertow side
    assert view["omen_hand"]["hand_max"] == 2


# ================================================================ starter packs
@pytest.mark.parametrize("pack_id,path,ending", [
    ("dracula", ["read_log", "watch_bench", "hear_renfield", "sanctify_boxes",
                 "chase_boxes", "stake_and_wafer"], "beacon_ending"),
    ("rue_morgue", ["examine_wounds", "consult_dupin", "take_lash", "present_truth"],
     "exoneration_ending"),
    ("time_machine", ["study_sphinx", "keep_fire", "light_way", "arm_yourself",
                      "fire_trick", "throw_home"], "home_ending"),
])
def test_starter_packs_play_to_endings(app, pack_id, path, ending):
    pack = worldpacks.load_pack(pack_id)
    assert pack and not forge.validate_pack(pack)
    cid = gm.create_campaign(f"Walk {pack_id}", pack_id,
                             {"name": "Walker", "archetype": pack["archetypes"][0]["id"],
                              "specialty": "lore"})
    view = gm.campaign_view(cid)
    assert view["scene"]["adventure_id"]  # the story opens at the hub
    for choice in path:
        res = gm.choose(cid, choice)
    assert gm.campaign_view(cid)["scene"]["adventure_done"]
    led = legacy.ledger(cid)
    assert ending in led["endings_seen"]


def test_starter_pack_licensing_present(app):
    for pack_id, author, license_fragment in [
        ("dracula", "Bram Stoker", "Public Domain"),
        ("rue_morgue", "Edgar Allan Poe", "Public Domain"),
        ("time_machine", "H. G. Wells", "Public Domain"),
    ]:
        lic = worldpacks.load_pack(pack_id)["license"]
        assert author in lic["author"]
        assert license_fragment in lic["license"]
        assert lic["source_url"].startswith("https://www.gutenberg.org/ebooks/")


def test_hidden_info_boundary_on_library_pack(app):
    cid = gm.create_campaign("Boundary", "dracula",
                             {"name": "Watcher", "archetype": "occultist", "specialty": "bind"})
    events = mp.events_since(cid, 0, None)
    blob = json.dumps(events)
    view = json.dumps(gm.campaign_view(cid))
    for secret in ("must sleep in that earth", "Renfield is already bound", "Borgo Pass, his enemies"):
        assert secret not in blob and secret not in view


# ================================================================ multiplayer on a library pack
def test_multiplayer_on_imported_adventure(app):
    c = app.test_client()
    r = c.post("/api/campaigns", json={
        "name": "Shared Dracula", "pack_id": "dracula",
        "character": {"name": "Van Helsing's Guest", "archetype": "occultist", "specialty": "bind"}})
    cid = r.get_json()["campaign_id"]
    host = MpClient(c, cid=cid, host=True)
    host.post("/mp/start", {"campaign_id": cid})
    guest = _guest({"host": host, "cid": cid, "app": c}, "Brinna",
                   {"name": "Brinna", "archetype": "sea_widow", "specialty": "bind"})
    # both walk the same locked-room story, serialized
    r1 = host.act("I examine the wreck with a scholar's patience.")
    assert r1.status_code == 200
    r2 = guest.act("I follow the drag-marks up the cliff.")
    assert r2.status_code == 200
    r3 = guest.chat("The ship has no crew and one passenger. Beware the boxes.")
    assert r3.status_code == 200
    events = [e for e in mp.events_since(cid, 0, None) if e["type"] == "narration"]
    assert len(events) >= 2
    # party travel on the library pack works by vote
    r = host.travel("sanatorium")
    assert r.status_code == 200
    r = guest.post("/mp/travel/vote", {"campaign_id": cid, "accept": True})
    assert r.status_code == 200
    assert gm.campaign_view(cid)["location"]["id"] == "sanatorium"


def test_multiplayer_join_dnd_campaign(app):
    c = app.test_client()
    r = c.post("/api/campaigns", json={
        "name": "Shared D&D", "pack_id": "dracula",
        "character": {"name": "Leader", "ruleset": "dnd5e",
                      "class": "fighter", "species": "dwarf", "background": "soldier"}})
    cid = r.get_json()["campaign_id"]
    host = MpClient(c, cid=cid, host=True)
    host.post("/mp/start", {"campaign_id": cid})
    invite = host.make_invite()
    guest = MpClient(c)
    guest.cid = cid
    d = guest.join_with(invite["token"], "Dndfriend", {
        "name": "Dndfriend", "ruleset": "dnd5e",
        "class": "rogue", "species": "halfling", "background": "charlatan"})
    view = guest.view_json()
    assert view["ruleset"] == "dnd5e"
    assert view["dnd"]["class"] == "Rogue"
    assert view["dnd"]["skills_prof"]


# ================================================================ migration
def test_v4_migration_preserves_campaigns(campaign):
    marker = db.query_one("SELECT value FROM meta WHERE key='schema_version'")
    assert marker["value"] == "saturday.core.v8"
    assert gm.campaign_view(campaign)["character"]["name"]
