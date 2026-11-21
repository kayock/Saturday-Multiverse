"""Saturday Multiverse — provider-independent AI Game Master adapter.

Talks to any OpenAI-compatible chat/completions endpoint: a local model
server (Ollama, LM Studio, llama.cpp, KoboldCpp, vLLM…), a LAN box, or a
remote provider. Nothing here is tied to one vendor, host, or region.

The adapter is deliberately tiny: one call, strict timeouts, typed errors,
and robust JSON extraction for the Game Master's structured contract.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from . import config, db

DEFAULT_AI_CONFIG = {
    "enabled": False,
    "provider": "openai-compatible",
    "base_url": "http://127.0.0.1:11434/v1",
    "model": "",
    "api_key": "",
    "temperature": 0.8,
    "max_tokens": 900,
    "narration_words": 220,
}


class AiError(Exception):
    """Raised with a user-readable message when a model call fails."""

    def __init__(self, detail: str, kind: str = "error"):
        super().__init__(detail)
        self.detail = detail
        self.kind = kind  # connection | auth | http | config | bad_response


def get_ai_config() -> dict:
    cfg = dict(DEFAULT_AI_CONFIG)
    stored = db.get_json_setting("ai_config", {})
    if isinstance(stored, dict):
        cfg.update({k: v for k, v in stored.items() if k in DEFAULT_AI_CONFIG})
    return cfg


def set_ai_config(patch: dict) -> dict:
    cfg = get_ai_config()
    for key in DEFAULT_AI_CONFIG:
        if key in patch:
            cfg[key] = patch[key]
    # validation
    cfg["temperature"] = max(0.0, min(2.0, float(cfg.get("temperature", 0.8))))
    cfg["max_tokens"] = max(120, min(4000, int(cfg.get("max_tokens", 900))))
    cfg["enabled"] = bool(cfg.get("enabled"))
    if cfg.get("provider") != "openai-compatible":
        raise ValueError("provider must be 'openai-compatible'")
    if not str(cfg.get("base_url", "")).startswith(("http://", "https://")):
        raise ValueError("base_url must be an http(s) URL")
    db.set_json_setting("ai_config", cfg)
    return cfg


def masked_ai_config() -> dict:
    """Client-safe view: the API key is never echoed back."""
    cfg = get_ai_config()
    out = dict(cfg)
    out["has_key"] = bool(cfg.get("api_key"))
    out["api_key"] = ""
    return out


# --------------------------------------------------------------------------
# The call itself
# --------------------------------------------------------------------------

def chat(messages: list[dict], cfg: dict | None = None) -> tuple[str, dict]:
    """One chat completion against the configured endpoint.

    Returns (content, meta) where meta carries timing and the model name.
    Raises AiError with a readable explanation on any failure.
    """
    cfg = cfg or get_ai_config()
    if not cfg.get("enabled"):
        raise AiError("AI Game Master is disabled. Open Settings → Model to enable it.", "config")
    if not cfg.get("model"):
        raise AiError("No model name is set. Open Settings → Model.", "config")

    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": float(cfg.get("temperature", 0.8)),
        "max_tokens": int(cfg.get("max_tokens", 900)),
        "stream": False,
    }
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"

    started = time.time()
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=config.AI_TIMEOUT_SECONDS) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
        except Exception:  # noqa: BLE001 - best effort body read
            pass
        kind = "auth" if exc.code in (401, 403) else "http"
        raise AiError(f"Model server answered HTTP {exc.code}: {detail or exc.reason}", kind) from exc
    except urllib.error.URLError as exc:
        raise AiError(
            f"Could not reach the model server at {cfg['base_url']} ({exc.reason}). "
            "Check that your local model server is running and the URL is correct.",
            "connection",
        ) from exc
    except TimeoutError as exc:
        raise AiError("The model server did not answer in time.", "connection") from exc
    except json.JSONDecodeError as exc:
        raise AiError("Model server returned malformed JSON.", "bad_response") from exc

    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AiError("Model response had no message content.", "bad_response") from exc

    meta = {
        "model": body.get("model", cfg["model"]),
        "latency_ms": int((time.time() - started) * 1000),
        "usage": body.get("usage", {}),
    }
    return content, meta


def test_connection(cfg: dict | None = None) -> dict:
    """Small end-to-end ping used by the model-configuration screen."""
    cfg = cfg or get_ai_config()
    try:
        content, meta = chat(
            [{"role": "user", "content": "Reply with exactly one word: READY"}], cfg
        )
        ok = "ready" in content.strip().lower()
        return {"ok": ok, "detail": content.strip()[:120], **meta}
    except AiError as exc:
        return {"ok": False, "detail": exc.detail, "kind": exc.kind}


# --------------------------------------------------------------------------
# Structured output extraction
# --------------------------------------------------------------------------

def extract_json(text: str) -> dict | None:
    """Pull the first balanced JSON object out of a model reply.

    Tolerates markdown fences, leading prose, and trailing chatter — small
    local models rarely emit pristine JSON.
    """
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # drop the first fence line and the last fence
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines)

    start = cleaned.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = cleaned[start : i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    return None
    return None
