"""Campaign Forge model selection.

This is independent of the Game Master that narrates play. Forge calls are
marked direct so gameplay routing cannot swap the endpoint. An online
provider is contacted only when the operator selected it and approved
sending the manuscript. A failed local choice never falls through to a
paid service, and nothing here starts a large model.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from . import ai, db

LARGE_BYTES = 2_600_000_000
JOB_KEY = "forge_job_ai"
SELECTIONS = ("auto_local", "local", "online")

DEFAULT = {
    "selection": "auto_local",
    "provider_name": "",
    "base_url": "",
    "model": "",
    "api_key": "",
    "temperature": 0.4,
    "max_tokens": 1600,
    "price_input_per_million": None,
    "price_output_per_million": None,
    "price_currency": "USD",
}


class ForgeAiError(ValueError):
    pass


def get_config() -> dict:
    cfg = dict(DEFAULT)
    stored = db.get_json_setting("forge_ai", {})
    if isinstance(stored, dict):
        for key in DEFAULT:
            if key in stored:
                cfg[key] = stored[key]
    if cfg["selection"] not in SELECTIONS:
        cfg["selection"] = "auto_local"
    return cfg


def set_config(patch: dict) -> dict:
    """Save Forge settings. Does not write the gameplay AI config."""
    cfg = get_config()
    if "selection" in patch:
        selection = str(patch["selection"] or "")
        if selection not in SELECTIONS:
            raise ForgeAiError("selection must be auto_local, local, or online")
        cfg["selection"] = selection
    for key, limit in (("provider_name", 80), ("base_url", 300), ("model", 160)):
        if key in patch:
            cfg[key] = str(patch[key] or "").strip()[:limit]
    if "api_key" in patch and str(patch["api_key"] or "").strip():
        cfg["api_key"] = str(patch["api_key"]).strip()[:400]
    if "temperature" in patch and patch["temperature"] is not None:
        cfg["temperature"] = max(0.0, min(1.5, float(patch["temperature"])))
    if "max_tokens" in patch and patch["max_tokens"] is not None:
        cfg["max_tokens"] = max(400, min(4000, int(patch["max_tokens"])))
    for key in ("price_input_per_million", "price_output_per_million"):
        if key in patch:
            raw = patch[key]
            if raw in (None, ""):
                cfg[key] = None
            else:
                cfg[key] = max(0.0, float(raw))
    if "price_currency" in patch:
        cfg["price_currency"] = str(patch["price_currency"] or "USD").strip()[:8] or "USD"
    if cfg["base_url"] and not str(cfg["base_url"]).startswith(("http://", "https://")):
        raise ForgeAiError("base_url must be an http(s) URL")
    db.set_json_setting("forge_ai", cfg)
    return masked()


def masked() -> dict:
    cfg = get_config()
    out = dict(cfg)
    out["has_key"] = bool(cfg.get("api_key"))
    out["api_key"] = ""
    return out


def locality(url: str) -> str:
    """local, online, or unknown (hostname that does not resolve)."""
    host = (urlparse(url or "").hostname or "").strip().lower()
    if not host:
        return "unknown"
    if host in ("localhost", "localhost.localdomain"):
        return "local"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        return "local" if _private(ip) else "online"
    if host.endswith((".local", ".lan", ".home", ".internal")):
        return "local"
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        # "mock" and "m" are unresolvable test names. A dotted public name
        # that does not resolve is still treated as off-network.
        return "unknown" if "." not in host else "online"
    addrs = []
    for info in infos:
        try:
            addrs.append(ipaddress.ip_address(info[4][0]))
        except ValueError:
            continue
    if addrs and all(_private(a) for a in addrs):
        return "local"
    if addrs:
        return "online"
    return "unknown"


def _private(ip: ipaddress._BaseAddress) -> bool:
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local)


def _direct(base_url: str, model: str, *, key: str = "", tier: str = "local",
            host: str = "", note: str = "", context: int = 0) -> dict:
    cfg = {
        "enabled": True,
        "provider": "openai-compatible",
        "base_url": base_url,
        "model": model,
        "api_key": key or "",
        "temperature": float(get_config().get("temperature") or 0.4),
        "max_tokens": int(get_config().get("max_tokens") or 1600),
        "narration_words": 220,
        "_direct": True,
        "_forge": True,
        "_tier": tier,
        "_host": host,
        "_route_note": note,
    }
    if context:
        cfg["_context"] = int(context)
    return cfg


def _pins() -> dict:
    stored = db.get_json_setting(JOB_KEY, {})
    return stored if isinstance(stored, dict) else {}


def pin_job(job_id: str, cfg: dict) -> None:
    """Remember which endpoint a job may use. The API key is never stored."""
    pins = _pins()
    pins[job_id] = {
        "base_url": cfg.get("base_url") or "",
        "model": cfg.get("model") or "",
        "locality": "online" if cfg.get("_tier") == "online" else "local",
        "approved": bool(cfg.get("_tier") == "online"),
        "provider_name": cfg.get("_provider") or "",
        "requires_loaded": bool(cfg.get("_requires_loaded")),
        "host": cfg.get("_host") or "",
        "tier": cfg.get("_tier") or "",
    }
    if len(pins) > 40:
        for old in list(pins)[:-40]:
            pins.pop(old, None)
    db.set_json_setting(JOB_KEY, pins)


def cfg_for_job(job_id: str) -> dict:
    pin = _pins().get(job_id)
    if not pin:
        return resolve(transmit_approved=False)
    if pin.get("locality") == "online":
        if not pin.get("approved"):
            raise ForgeAiError(_approval_message(pin.get("provider_name") or "", pin.get("base_url") or ""))
        key = ""
        cur = get_config()
        if (cur["selection"] == "online"
                and _same(cur.get("base_url") or "", pin.get("base_url") or "")):
            key = cur.get("api_key") or ""
        return _direct(pin["base_url"], pin["model"], key=key, tier="online",
                       host=pin.get("host") or "online",
                       note="online conversion approved for this job")
    if pin.get("requires_loaded") and not _is_loaded(pin.get("base_url") or "", pin.get("model") or ""):
        raise ForgeAiError(
            f"{pin.get('model')} is not running. Start it yourself and retry. "
            "Campaign Forge will not start a large model, and it will not switch to an online provider.")
    return _direct(pin["base_url"], pin["model"], tier=pin.get("tier") or "local",
                   host=pin.get("host") or "local",
                   note="pinned local conversion model")


def resolve(transmit_approved: bool = False) -> dict:
    """Choose the Forge endpoint. Raises ForgeAiError; never calls a model."""
    cfg = get_config()
    if cfg["selection"] == "online":
        return _online(cfg, transmit_approved)
    if cfg["selection"] == "local":
        return _selected_local(cfg)
    return _auto_local()


def _auto_local() -> dict:
    gm = ai.get_ai_config()
    if not gm.get("enabled") or not str(gm.get("model") or "").strip():
        raise ForgeAiError(
            "the Forge needs an AI model — configure one in Model & Settings first")
    where = locality(gm.get("base_url") or "")
    if where == "online":
        raise ForgeAiError(
            "The Game Master endpoint is outside the local network. Campaign Forge will not "
            "send manuscript text there unless you select an online provider and approve that "
            "conversion. Nothing was sent.")
    if where == "local":
        upgraded = _loaded_advanced()
        if upgraded:
            return upgraded
    return _direct(gm["base_url"], gm["model"], key="", tier="light", host="configured",
                   note="automatic local conversion uses the configured local model")


def _selected_local(cfg: dict) -> dict:
    url = (cfg.get("base_url") or "").strip()
    model = (cfg.get("model") or "").strip()
    if not url or not model:
        raise ForgeAiError("Choose a local endpoint and model for Campaign Forge.")
    if locality(url) == "online":
        raise ForgeAiError(
            "That endpoint is outside the local network. Select an online provider and approve "
            "transmission. Nothing was sent.")
    rec = _find_model(url, model)
    if rec and int(rec.get("size") or 0) >= LARGE_BYTES and not rec.get("loaded"):
        raise ForgeAiError(
            f"{model} is not running. Start it yourself before converting. "
            "Campaign Forge will not start a large model. Nothing was sent.")
    if rec is None and not model.startswith("saturday-gm-"):
        raise ForgeAiError(
            f"Could not confirm {model} is already running on a local server. "
            "Campaign Forge will not start it. Nothing was sent.")
    out = _direct(url, model, tier="local", host=rec.get("host") if rec else "local",
                  note="selected local conversion model",
                  context=int((rec or {}).get("context") or 0))
    if rec and int(rec.get("size") or 0) >= LARGE_BYTES:
        out["_requires_loaded"] = True
    return out


def _online(cfg: dict, transmit_approved: bool) -> dict:
    url = (cfg.get("base_url") or "").strip()
    model = (cfg.get("model") or "").strip()
    if not url or not model:
        raise ForgeAiError("Set an online endpoint and model before converting.")
    if locality(url) == "local":
        return _selected_local(cfg)
    if not transmit_approved:
        raise ForgeAiError(_approval_message(cfg.get("provider_name") or "", url))
    out = _direct(url, model, key=cfg.get("api_key") or "", tier="online", host="online",
                  note="online conversion explicitly approved")
    out["_provider"] = cfg.get("provider_name") or ""
    return out


def _approval_message(provider: str, url: str) -> str:
    host = urlparse(url or "").hostname or "the provider"
    name = provider or host
    return (f"Manuscript text would leave the local network and be sent to {name} ({host}). "
            "Approve this conversion before it starts. Nothing was sent.")


def _same(a: str, b: str) -> bool:
    return a.rstrip("/").lower() == b.rstrip("/").lower()


def _snapshot() -> dict:
    try:
        from . import routing
        return routing.snapshot()
    except Exception:  # noqa: BLE001 - discovery must not take the Forge down
        return {}


def _find_model(url: str, model: str) -> dict | None:
    want = model.split(":", 1)[0]
    snap = _snapshot()
    from . import routing
    for host in ("station", "portable"):
        info = snap.get(host) or {}
        host_url = (routing.get_routing().get(f"{host}_url") or "")
        if host_url and not _same(routing.ollama_root(host_url), routing.ollama_root(url)) and not _same(host_url, url):
            continue
        if not info.get("ok"):
            continue
        loaded = {m.get("name", "").split(":", 1)[0] for m in info.get("loaded") or []}
        for m in info.get("models") or []:
            name = m.get("name") or ""
            if name.split(":", 1)[0] == want or name == model:
                return {"name": name, "size": int(m.get("size") or 0),
                        "loaded": name.split(":", 1)[0] in loaded, "host": host,
                        "context": int(m.get("context") or 0)}
    return None


def _is_loaded(url: str, model: str) -> bool:
    rec = _find_model(url, model)
    return bool(rec and rec.get("loaded"))


def _loaded_advanced() -> dict | None:
    snap = _snapshot()
    from . import routing
    routing_cfg = routing.get_routing()
    for host in ("portable", "station"):
        info = snap.get(host) or {}
        if not info.get("ok"):
            continue
        loaded = {m.get("name", "").split(":", 1)[0] for m in info.get("loaded") or []}
        for m in info.get("models") or []:
            name = m.get("name") or ""
            bare = name.split(":", 1)[0]
            if bare not in loaded or bare.startswith("saturday-gm-"):
                continue
            if int(m.get("size") or 0) < LARGE_BYTES:
                continue
            base = routing_cfg.get(f"{host}_url") or ""
            if not base:
                continue
            out = _direct(base, name, tier="advanced", host=host,
                          note="using a larger local model that is already running",
                          context=int(m.get("context") or 0))
            out["_requires_loaded"] = True
            return out
    return None


def catalog() -> dict:
    """Local models the Forge may use. Does not load or start any model."""
    snap = _snapshot()
    from . import routing
    routing_cfg = routing.get_routing()
    light, advanced = [], []
    for host in ("station", "portable"):
        info = snap.get(host) or {}
        if not info.get("ok"):
            continue
        base = routing_cfg.get(f"{host}_url") or ""
        loaded = {m.get("name", "").split(":", 1)[0] for m in info.get("loaded") or []}
        for m in info.get("models") or []:
            name = m.get("name") or ""
            if not name or "embed" in name.lower():
                continue
            size = int(m.get("size") or 0)
            row = {"host": host, "base_url": base, "model": name, "size": size,
                   "loaded": name.split(":", 1)[0] in loaded, "locality": "local",
                   "context": int(m.get("context") or 0)}
            if name.startswith("saturday-gm-") or (size and size < LARGE_BYTES):
                light.append(row)
            else:
                advanced.append(row)
    gm = ai.masked_ai_config()
    return {
        "forge": masked(),
        "gameplay_model": gm.get("model") or "",
        "gameplay_enabled": bool(gm.get("enabled")),
        "lightweight": light,
        "advanced": advanced,
        "online_configured": get_config()["selection"] == "online" and bool(get_config()["model"]),
    }


def preview(doc_chars: int) -> dict:
    """Describe the conversion that would run. Does not contact a provider."""
    cfg = get_config()
    gm = ai.get_ai_config()
    selection = cfg["selection"]
    if selection == "online":
        where = "online"
        model = cfg.get("model") or ""
        provider = cfg.get("provider_name") or (urlparse(cfg.get("base_url") or "").hostname or "")
        needs_approval = locality(cfg.get("base_url") or "") != "local"
    elif selection == "local":
        where = "local"
        model = cfg.get("model") or ""
        provider = "local"
        needs_approval = False
    else:
        where = locality(gm.get("base_url") or "") if gm.get("enabled") else "unavailable"
        if where == "online":
            where = "blocked"
        model = gm.get("model") or ""
        provider = "local"
        needs_approval = False
    chars = max(0, int(doc_chars or 0))
    windows = max(1, -(-chars // 9000)) if chars else 0
    calls = windows + 2 if windows else 0
    tokens_in = int(chars / 4) + 800 if chars else 0
    tokens_out = calls * 600
    pin = cfg.get("price_input_per_million")
    pout = cfg.get("price_output_per_million")
    cost = None
    pricing = "unavailable"
    note = "No operator-supplied price. This is not a quote."
    if where == "online" and pin is not None and pout is not None:
        cost = round((tokens_in / 1_000_000) * float(pin) + (tokens_out / 1_000_000) * float(pout), 4)
        pricing = "operator"
        note = ("Estimate from the prices you entered and about four characters per token. "
                "Not a provider quote.")
    return {
        "selection": selection,
        "locality": where,
        "provider": provider,
        "model": model,
        "needs_approval": needs_approval,
        "windows": windows,
        "calls": calls,
        "tokens_in_estimate": tokens_in,
        "tokens_out_estimate": tokens_out,
        "cost_estimate": cost,
        "currency": cfg.get("price_currency") or "USD",
        "pricing": pricing,
        "note": note,
        "gameplay_model": ai.masked_ai_config().get("model") or "",
    }


def window_chars(cfg: dict | None) -> int:
    """Never smaller than the existing 9,000-character window."""
    ctx = int((cfg or {}).get("_context") or 0)
    if ctx < 8192:
        return 9000
    return min(24000, max(9000, (ctx - 2048) * 3))
