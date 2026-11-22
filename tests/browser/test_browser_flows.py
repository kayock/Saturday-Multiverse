"""Browser acceptance flows for Saturday Multiverse (Playwright).

These are REAL browser sessions. They are excluded from the default pytest
run (tests/browser has its own invocation) so environments without browsers
still get a green unit/API suite.
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def server_url():
    port = _free_port()
    env = dict(os.environ)
    env["SATURDAY_DATA_DIR"] = str(ROOT / "userdata-browser-test")
    env["SATURDAY_PORT"] = str(port)
    proc = subprocess.Popen([sys.executable, "-m", "server.app"], cwd=str(ROOT),
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            urllib.request.urlopen(base + "/api/health", timeout=2)
            break
        except Exception:
            time.sleep(0.3)
    else:
        proc.kill()
        pytest.fail("server did not start")
    yield base
    proc.terminate()
    proc.wait(timeout=10)
    import shutil
    shutil.rmtree(ROOT / "userdata-browser-test", ignore_errors=True)


def _new_page(pw_browser):
    ctx = pw_browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    return ctx, page


def test_title_and_tutorial(server_url):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            ctx, page = _new_page(browser)
            page.goto(server_url)
            expect(page.get_by_role("heading", name="SATURDAY MULTIVERSE")).to_be_visible()
            # the first-run tutorial appears and can be skipped
            page.wait_for_timeout(1200)
            skip = page.get_by_role("button", name="Skip")
            if skip.count():
                skip.click()
            expect(page.get_by_role("button", name="New Voyage")).to_be_visible()
        finally:
            ctx.close()
            browser.close()


def test_solo_voyage_shore_and_recap(server_url):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            ctx, page = _new_page(browser)
            page.goto(server_url)
            page.wait_for_timeout(1100)
            skip = page.get_by_role("button", name="Skip")
            if skip.count():
                skip.click()
            page.get_by_role("button", name="New Voyage").click()
            page.get_by_role("textbox", name="NAME").fill("Playwright Sailor")
            page.get_by_text("D&D-compatible (SRD)").click()
            page.get_by_role("button", name="Step through the foam").click()
            expect(page.get_by_role("button", name="Trace")).to_be_visible(timeout=15000)
            # act once, then read the Engine Trace panel
            page.get_by_placeholder("What do you do?").fill("I walk the tideline")
            page.get_by_role("button", name="Act").click()
            page.wait_for_timeout(2500)
            page.get_by_role("button", name="Trace").click()
            expect(page.get_by_role("heading", name="Engine Trace")).to_be_visible()
            # the trace cites the narration source honestly
            expect(page.get_by_text("Offline Storyteller (built-in)").first).to_be_visible()
        finally:
            ctx.close()
            browser.close()


def test_ledger_goal_campfire_checkpoint(server_url):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            ctx, page = _new_page(browser)
            page.goto(server_url)
            page.wait_for_timeout(1100)
            skip = page.get_by_role("button", name="Skip")
            if skip.count():
                skip.click()
            page.get_by_role("button", name="New Voyage").click()
            page.get_by_role("textbox", name="NAME").fill("Ledger Tester")
            # stable selectors: the pack chip in the New Voyage picker (plain
            # text also matches the dock title) and the dock's own Ledger
            # button (the character HUD button's accessible name also
            # contains "Ledger")
            page.locator('[data-pack="living_shore"]').click()
            page.get_by_role("button", name="Step through the foam").click()
            page.locator('#hud-nav [data-panel="ledger"]').click()
            expect(page.get_by_role("heading", name="Expedition goals")).to_be_visible()
            page.locator("#goal-title").fill("Recover three lost relics")
            page.locator("#goal-add").click()
            expect(page.get_by_text("Recover three lost relics")).to_be_visible()
            expect(page.get_by_role("heading", name="Campfire stories")).to_be_visible()
            page.locator("#fire-text").fill("We watched the lights and made an oath.")
            page.locator("#fire-add").click()
            expect(page.get_by_text("We watched the lights and made an oath.")).to_be_visible()
        finally:
            ctx.close()
            browser.close()


def test_workshop_playtest_button(server_url):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            ctx, page = _new_page(browser)
            page.goto(server_url)
            page.get_by_role("button", name="The Infinite Library").click()
            page.get_by_role("button", name="Worldbuilding Workshop").click()
            page.get_by_role("textbox", name="Name your world").fill("Browser Built")
            page.get_by_role("button", name="Open a new world").click()
            expect(page.get_by_role("button", name="Playtest in an isolated portal")
                   ).to_be_visible()
            page.get_by_role("button", name="Playtest in an isolated portal").click()
            page.wait_for_timeout(2000)
        finally:
            ctx.close()
            browser.close()
