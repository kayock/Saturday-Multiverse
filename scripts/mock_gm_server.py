#!/usr/bin/env python3
"""A tiny OpenAI-compatible mock model server, for testing and demos.

Listens like a chat/completions endpoint and always answers with a valid
Game Master JSON contract. Useful to verify Saturday Multiverse's AI
pipeline end-to-end without a real model, or as a placeholder while you
set up your own provider.

    python3 scripts/mock_gm_server.py            # port 8090
    python3 scripts/mock_gm_server.py 8091
"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class MockGMHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.rstrip("/").endswith("/health"):
            self._json({"ok": True})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        user_text = " ".join(
            m.get("content", "") for m in body.get("messages", []) if m.get("role") == "user"
        ).lower()

        # vary the response a little by what the player did
        if "listen" in user_text or "walk" in user_text:
            narration = (
                "You walk the tideline and listen. The doors say nothing, but the "
                "sea between them is warmer than it should be, and a tenth lantern "
                "of dark glass sits at the end of the far row."
            )
            check = None
        elif "ask" in user_text or "speak" in user_text:
            narration = (
                "You speak your question into the mist. The mist takes it politely "
                "and gives back the smell of lamp oil. Somewhere out on the water, "
                "a switch is thrown and a signal begins."
            )
            check = {"skill": "notice", "hard": False, "reason": "spotting the signal source",
                     "harm_type": "nerve"}
        else:
            narration = (
                "The shore considers your intent. Sand shifts underfoot; the Beam "
                "hums; one of the three doors exhales a slow glow of violet light. "
                "Whatever you meant, the shore is willing to let you try."
            )
            check = None

        content = json.dumps({
            "narration": narration,
            "npc_lines": [],
            "check": check,
            "inventory_request": [{"action": "give", "item_id": "dried_kelp", "qty": 1}] if "kelp" in user_text else None,
            "memory": {
                "facts": ["The sea between the doors is warmer than it should be."],
                "hidden_note": "The dark tenth lantern is counting the player's visits.",
                "relationships": {},
            },
            "choices": ["Walk toward the warmer water", "Listen at the sealed door"],
            "scene_hint": "Tenth Lantern",
        })
        self._json({
            "id": "mock-completion", "object": "chat.completion", "model": "mock-gm-1",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 120, "total_tokens": 130},
        })

    def _json(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # quiet
        pass


def serve(port=8090):
    server = ThreadingHTTPServer(("127.0.0.1", port), MockGMHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8090
    print(f"mock GM listening on http://127.0.0.1:{port}/v1 — configure this as your endpoint URL")
    ThreadingHTTPServer(("127.0.0.1", port), MockGMHandler).serve_forever()
