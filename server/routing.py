"""Intelligent Game Master routing.

The application — not the model — chooses which OpenAI-compatible endpoint
narrates a turn. Ordinary gameplay stays on one lightweight model. A larger
model is consulted only for Campaign Forge work, only when escalation is
enabled, and only when that exact model is already loaded. Nothing here
starts a large model, and a failed choice falls back to the single endpoint
configured in Settings (and from there, the Offline Storyteller).

Manual mode returns the configured endpoint unchanged, so existing saves
and tests behave exactly as before.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from . import db

MODES = ("auto", "prefer_station", "prefer_portable", "manual")
LIGHT_NAMES_DEFAULT = ("saturday-gm-gamemaster", "saturday-gm-gemmasutra")
# Larger than either installed Q4 2B Game Master (about 1.3–1.7 GB).
LARGE_BYTES = 2_600_000_000
CACHE_SECONDS = 12
STICKY_SECONDS = 90

_cache = {"at": 0.0, "data": None}
_sticky = {"until": 0.0, "choice": None}
_latency = {}  # host id -> last successful latency ms
_last = {
    "model": "",
    "host": "",
    "tier": "",
    "latency_ms": None,
    "note": "",
    "at": 0.0,
}


def defaults() -> dict:
    auto = os.environ.get("SATURDAY_GM_AUTO", "").strip() == "1"
    return {
        "mode": "auto" if auto else "manual",
        "escalation": "on",
        "primary_model": os.environ.get("SATURDAY_GM_PRIMARY", LIGHT_NAMES_DEFAULT[0]),
        "fallback_model": os.environ.get("SATURDAY_GM_FALLBACK", LIGHT_NAMES_DEFAULT[1]),
        "advanced_base_url": "",
        "advanced_model": "",
        "station_url": os.environ.get("SATURDAY_GM_STATION_URL", "http://127.0.0.1:11434/v1"),
        "portable_url": os.environ.get("SATURDAY_GM_PORTABLE_URL", ""),
    }


def get_routing() -> dict:
    cfg = defaults()
    try:
        stored = db.get_json_setting("ai_routing", {})
    except Exception:  # noqa: BLE001 - routing must never block a turn
        stored = {}
    if isinstance(stored, dict):
        for key in cfg:
            if key in stored and stored[key] is not None:
                cfg[key] = stored[key]
    if cfg["mode"] not in MODES:
        cfg["mode"] = "manual"
    if cfg["escalation"] not in ("on", "off"):
        cfg["escalation"] = "off"
    return cfg


def set_routing(patch: dict) -> dict:
    cfg = get_routing()
    if "mode" in patch:
        mode = str(patch["mode"])
        if mode not in MODES:
            raise ValueError("mode must be auto, prefer_station, prefer_portable, or manual")
        cfg["mode"] = mode
    if "escalation" in patch:
        val = patch["escalation"]
        if val in (True, "on", "auto"):
            cfg["escalation"] = "on"
        elif val in (False, "off", ""):
            cfg["escalation"] = "off"
        else:
            raise ValueError("escalation must be on or off")
    for key, limit in (("primary_model", 120), ("fallback_model", 120), ("advanced_model", 120)):
        if key in patch:
            cfg[key] = str(patch[key] or "").strip()[:limit]
    for key in ("advanced_base_url", "station_url", "portable_url"):
        if key in patch:
            url = str(patch[key] or "").strip()
            if url and not url.startswith(("http://", "https://")):
                raise ValueError(f"{key} must be an http(s) URL")
            cfg[key] = url
    clear_state()
    db.set_json_setting("ai_routing", cfg)
    return cfg


def clear_state() -> None:
    """Drop cached probes and the sticky host. Called when settings change."""
    _cache["at"] = 0.0
    _cache["data"] = None
    _sticky["until"] = 0.0
    _sticky["choice"] = None


def last_route() -> dict:
    return dict(_last)


def note_narration(ai_used: bool) -> None:
    """Record whether the last turn's prose came from a model.

    A planned endpoint is not the same thing as AI narration. The title
    badge reads this so an Offline Storyteller turn is never labeled as
    model output.
    """
    _last["narration"] = "ai" if ai_used else "offline"
    _last["fallback"] = not ai_used


def fetch_json(url: str, timeout: float = 1.2):
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def ollama_root(base_url: str) -> str:
    url = (base_url or "").rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3]
    return url


def _bare(name: str) -> str:
    return (name or "").split(":", 1)[0].strip()


def _is_embed(name: str) -> bool:
    n = name.lower()
    return "embed" in n or n.startswith("nomic")


def inspect_ollama(base_url: str) -> dict:
    if not base_url:
        return {"ok": False, "error": "not configured", "models": [], "loaded": [], "busy": False}
    root = ollama_root(base_url)
    try:
        tags = fetch_json(root + "/api/tags", 1.2)
        ps = fetch_json(root + "/api/ps", 1.2)
    except Exception as exc:  # noqa: BLE001 - offline host is a normal outcome
        return {"ok": False, "error": str(exc.reason if isinstance(exc, urllib.error.URLError) else exc)[:160],
                "models": [], "loaded": [], "busy": False}
    models = []
    for m in tags.get("models") or []:
        models.append({
            "name": m.get("name") or "",
            "size": int(m.get("size") or 0),
            "param": str((m.get("details") or {}).get("parameter_size") or ""),
        })
    loaded = []
    busy = False
    for m in ps.get("models") or []:
        name = m.get("name") or m.get("model") or ""
        size = int(m.get("size") or 0)
        loaded.append({"name": name, "size": size})
        # Another resident model means this host is already working.
        # Loading a Game Master beside it can evict that model.
        if not _bare(name).startswith("saturday-gm-"):
            busy = True
    return {"ok": True, "error": "", "models": models, "loaded": loaded, "busy": busy}


def inspect_openai(base_url: str) -> dict:
    """Discover an already-running OpenAI-compatible server. Never starts it."""
    if not base_url:
        return {"ok": False, "ids": [], "error": "not configured"}
    root = base_url.rstrip("/")
    url = root if root.endswith("/models") else root + "/models"
    try:
        body = fetch_json(url, 1.2)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "ids": [], "error": str(exc)[:160]}
    ids = []
    for item in body.get("data") or []:
        mid = item.get("id") or ""
        if mid:
            ids.append(mid)
    return {"ok": True, "ids": ids, "error": "", "base_url": base_url.rstrip("/")}


def snapshot(force: bool = False) -> dict:
    now = time.time()
    if not force and _cache["data"] is not None and now - _cache["at"] < CACHE_SECONDS:
        return _cache["data"]
    routing = get_routing()
    discover = [u.strip() for u in os.environ.get("SATURDAY_GM_DISCOVER", "").split(",") if u.strip()]
    data = {"station": {}, "portable": {}, "extra": []}
    with ThreadPoolExecutor(max_workers=4) as pool:
        fut_s = pool.submit(inspect_ollama, routing["station_url"])
        fut_p = pool.submit(inspect_ollama, routing["portable_url"])
        fut_e = [pool.submit(inspect_openai, url) for url in discover]
        data["station"] = fut_s.result()
        data["portable"] = fut_p.result()
        for url, fut in zip(discover, fut_e):
            info = fut.result()
            info["base_url"] = url.rstrip("/")
            info["id"] = url
            data["extra"].append(info)
    _cache["at"] = time.time()
    _cache["data"] = data
    return data


def _has(info: dict, model: str) -> bool:
    want = _bare(model)
    if not want:
        return False
    return any(_bare(m.get("name", "")) == want for m in info.get("models") or [])


def _loaded(info: dict, model: str) -> bool:
    want = _bare(model)
    return any(_bare(m.get("name", "")) == want for m in info.get("loaded") or [])


def _host_order(routing: dict, snap: dict) -> list[str]:
    mode = routing["mode"]
    if mode == "prefer_station":
        return ["station", "portable"]
    if mode == "prefer_portable":
        return ["portable", "station"]
    portable_ok = snap["portable"].get("ok") and not snap["portable"].get("busy")
    station_ok = snap["station"].get("ok") and not snap["station"].get("busy")
    if portable_ok and station_ok:
        p_lat = _latency.get("portable")
        s_lat = _latency.get("station")
        if p_lat and s_lat and p_lat > max(20000, s_lat * 2):
            return ["station", "portable"]
        return ["portable", "station"]
    if portable_ok:
        return ["portable", "station"]
    return ["station", "portable"]


def purpose_of(messages: list[dict] | None) -> str:
    """The application classifies the call. The model does not get a vote."""
    for msg in messages or []:
        if msg.get("role") == "system" and "Campaign Forge" in (msg.get("content") or ""):
            return "forge"
    return "gameplay"


def _advanced(routing: dict, snap: dict) -> dict | None:
    if routing.get("escalation") != "on":
        return None
    base = (routing.get("advanced_base_url") or "").strip()
    model = (routing.get("advanced_model") or "").strip()
    if not base or not model:
        return None
    want = _bare(model)
    for host in ("station", "portable"):
        host_url = routing.get(f"{host}_url") or ""
        if host_url and ollama_root(host_url) == ollama_root(base):
            # Already loaded only. A request to a cold large model would start it.
            if _loaded(snap[host], model):
                return {"host": host, "base_url": base if base.rstrip("/").endswith("/v1") else base.rstrip("/") + "/v1",
                        "model": model, "tier": "advanced",
                        "note": "using the advanced model already running on " + host}
            return None
    for extra in snap.get("extra") or []:
        if not extra.get("ok"):
            continue
        extra_base = (extra.get("base_url") or "").rstrip("/")
        if ollama_root(extra_base) != ollama_root(base) and extra_base != base.rstrip("/"):
            continue
        ids = [_bare(i) for i in extra.get("ids") or []]
        if want in ids or model in (extra.get("ids") or []):
            url = base if base.rstrip("/").endswith("/v1") else base.rstrip("/") + "/v1"
            return {"host": "shared", "base_url": url, "model": model, "tier": "advanced",
                    "note": "using an already-running shared model; ordinary turns still use the lightweight Game Master"}
    return None


def choose(messages: list[dict] | None = None) -> dict | None:
    """Pick an endpoint, or None to keep the Settings endpoint exactly."""
    routing = get_routing()
    if routing["mode"] == "manual":
        return None
    snap = snapshot()
    purpose = purpose_of(messages)
    if purpose == "forge":
        advanced = _advanced(routing, snap)
        if advanced:
            return advanced
    # Sticky host keeps one turn's narration and its dice-reaction on the same voice.
    sticky = _sticky["choice"]
    if purpose == "gameplay" and sticky and time.time() < _sticky["until"]:
        info = snap.get(sticky["host"]) or {}
        if info.get("ok") and not info.get("busy") and _has(info, sticky["model"]):
            return dict(sticky)
    notes = []
    if routing["mode"] == "auto":
        portable = snap.get("portable") or {}
        if routing.get("portable_url"):
            if not portable.get("ok"):
                notes.append("portable offline")
            elif portable.get("busy"):
                notes.append("portable busy")
    names = [routing["primary_model"], routing["fallback_model"]]
    for host in _host_order(routing, snap):
        info = snap.get(host) or {}
        if not info.get("ok"):
            notes.append(f"{host} offline")
            continue
        if info.get("busy"):
            notes.append(f"{host} busy")
            continue
        for name in names:
            if not name:
                continue
            if _has(info, name):
                fallback = name == routing["fallback_model"] and name != routing["primary_model"]
                if fallback:
                    notes.append(f"primary unavailable, using {name}")
                return {
                    "host": host,
                    "base_url": routing[f"{host}_url"],
                    "model": _bare(name),
                    "tier": "light",
                    "note": "; ".join(n for n in notes if n),
                }
            notes.append(f"{name} not installed on {host}")
    return None


def apply(cfg: dict, messages: list[dict] | None) -> dict:
    """Overlay the chosen endpoint onto a copy of the AI config."""
    try:
        decision = choose(messages)
    except Exception:  # noqa: BLE001 - a routing failure must still allow the configured endpoint
        return cfg
    if not decision:
        return cfg
    out = dict(cfg)
    out["base_url"] = decision["base_url"]
    out["model"] = decision["model"]
    out["enabled"] = True
    out["_host"] = decision["host"]
    out["_tier"] = decision["tier"]
    out["_route_note"] = decision.get("note") or ""
    if decision["tier"] == "light":
        _sticky["choice"] = {
            "host": decision["host"],
            "base_url": decision["base_url"],
            "model": decision["model"],
            "tier": "light",
            "note": decision.get("note") or "",
        }
        _sticky["until"] = time.time() + STICKY_SECONDS
    return out


def remember(cfg: dict, latency_ms: int | None) -> None:
    host = cfg.get("_host") or ""
    if host and latency_ms is not None:
        _latency[host] = int(latency_ms)
    _last.update({
        "model": cfg.get("model") or "",
        "host": host,
        "tier": cfg.get("_tier") or "",
        "latency_ms": latency_ms,
        "note": cfg.get("_route_note") or "",
        "at": time.time(),
    })


def _advanced_options(routing: dict, snap: dict) -> list[dict]:
    options = []
    seen = set()

    def add(host, base, name, size, loaded, shared=False):
        bare = _bare(name)
        if not bare or _is_embed(bare) or bare.startswith("saturday-gm-"):
            return
        if size and size < LARGE_BYTES and not shared:
            return
        key = (ollama_root(base), bare)
        if key in seen:
            return
        seen.add(key)
        url = base if str(base).rstrip("/").endswith("/v1") else str(base).rstrip("/") + "/v1"
        options.append({
            "host": host,
            "base_url": url,
            "model": name if ":" in name or shared else bare,
            "loaded": bool(loaded),
            "size": int(size or 0),
            "shared": bool(shared),
        })

    for host in ("station", "portable"):
        info = snap.get(host) or {}
        loaded = {_bare(m.get("name", "")) for m in info.get("loaded") or []}
        for m in info.get("models") or []:
            add(host, routing.get(f"{host}_url") or "", m.get("name") or "", m.get("size") or 0,
                _bare(m.get("name") or "") in loaded)
    for extra in snap.get("extra") or []:
        if not extra.get("ok"):
            continue
        for mid in extra.get("ids") or []:
            add("shared", extra.get("base_url") or "", mid, LARGE_BYTES, True, shared=True)
    options.sort(key=lambda o: (not o["loaded"], o["host"], o["model"]))
    return options


def fleet_status() -> dict:
    routing = get_routing()
    snap = snapshot(force=True)
    plan = None
    saved_mode = routing["mode"]
    if saved_mode != "manual":
        plan = choose([{"role": "system", "content": "Game Master"}, {"role": "user", "content": "status"}])
    hosts = {}
    for host in ("station", "portable"):
        info = snap.get(host) or {}
        hosts[host] = {
            "ok": bool(info.get("ok")),
            "busy": bool(info.get("busy")),
            "error": info.get("error") or "",
            "has_primary": _has(info, routing["primary_model"]),
            "has_fallback": _has(info, routing["fallback_model"]),
            "loaded": [m.get("name") for m in info.get("loaded") or []],
        }
    return {
        "routing": routing,
        "hosts": hosts,
        "plan": plan,
        "last": last_route(),
        "advanced_options": _advanced_options(routing, snap),
        "escalation_ready": _advanced(routing, snap) is not None,
    }
