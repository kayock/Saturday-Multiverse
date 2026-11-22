# AI Game Master — provider guide

The Game Master speaks **OpenAI-compatible chat completions**. That single dialect
covers local model servers, LAN boxes, and hosted providers. Nothing in the code knows
or cares which one you use.

## Configuration

Open **Settings → Model** in the game (also reachable from the title screen):

- **Endpoint URL** — the base including `/v1` (the app appends `/chat/completions`).
- **Model name** — exactly as your server reports it.
- **API key** — optional; sent as `Authorization: Bearer …` only to your endpoint.
  Stored in your local SQLite database, never echoed back to the browser.
- **Creativity** (temperature) and **Narration length** (target words per turn).
- **Save**, then **Test connection** — a one-word ping that reports latency.

## Recipes

| You run | Endpoint URL | Model name |
|---|---|---|
| Ollama (`ollama serve`) | `http://127.0.0.1:11434/v1` | e.g. `qwen2.5:7b-instruct`, `llama3.1:8b` |
| LM Studio | `http://127.0.0.1:1234/v1` | the loaded model's id |
| llama.cpp server | `http://127.0.0.1:8080/v1` | any name (e.g. `local-model`) |
| KoboldCpp (OpenAI mode) | `http://127.0.0.1:5001/v1` | any name |
| vLLM | `http://HOST:8000/v1` | served model name |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini`, `gpt-4o`, … |
| OpenRouter | `https://openrouter.ai/api/v1` | e.g. `anthropic/claude-3.5-sonnet` |
| Together / Fireworks / Groq | their `/v1` base | their model ids |

**Recommendation for the tone of this game:** a mid-size instruct model (7–14B) at
temperature 0.7–0.9. The GM asks are short and structured; small local models do fine,
but they must be able to emit a JSON object reliably.

No model handy? `python scripts/mock_gm_server.py` starts a tiny OpenAI-compatible
mock at `http://127.0.0.1:8090/v1` (model `mock-gm-1`) that always answers in contract
— useful for demos and tests.

## What the model may and may not do

The system prompt (see `server/gm.py::build_system_prompt`) locks the model into a
JSON contract:

```json
{
  "narration": "second-person, present tense, ≤ N words",
  "npc_lines": [{"npc": "<npc_id>", "line": "dialogue"}],
  "check": {"skill": "notice|lore|persuade|fight|endure|bind",
            "hard": false, "reason": "…", "harm_type": "vigor|nerve"},
  "inventory_request": [{"action": "give|take", "item_id": "<catalog id>", "qty": 1}],
  "memory": {"facts": ["…"], "hidden_note": "secret", "relationships": {"npc_id": 1}},
  "choices": ["suggested action", "…"],
  "scene_hint": "three words"
}
```

- It may **request** one check per turn — the app rolls `2d6` (crypto RNG) and applies
  the Undertow bands and harm.
- It may **request** inventory changes — the app validates ids against the pack catalog
  and decides.
- It may store **memory facts** and one **hidden note** — hidden notes never appear in
  prompts or the client view.
- It may **not** narrate dice results, grant injuries in prose, or decide the player's
  actions. Malformed replies get one strict retry, then the Offline Storyteller takes
  over and the turn is labeled accordingly.

Prompt assembly: pack lore (trimmed), GM style, character sheet, tide/weather, scene
brief + directive, item catalog, NPC list, open quests, known facts, last 8 transcript
messages. The omen card in play is passed as atmosphere only.

## Campaign Forge uses its own model

The endpoint in Settings → Model narrates the game. Campaign Forge does not
have to use it.

On **Forge a campaign**, Conversion AI offers:

| Choice | What it does |
|---|---|
| Automatic local | Uses the configured local model. If a larger local model is already running, Forge may use that instead. It will not start one, and it will not send the book to a public endpoint. |
| Select local model | Uses one model discovered on a local or LAN server. A large model is used only while it is already running. |
| Online provider | Any OpenAI-compatible hosted API. You name the provider, endpoint, and model, and you may store an optional key. |

Before an online conversion, the screen states that the manuscript will
leave the local network. The server refuses the job until that conversion
is approved. Approving a connection test does not approve sending the book.
The key is stored only in the local database and is not written into the
job, the draft, or an export.

If you enter a price per million input tokens and a price per million
output tokens, Forge shows a rough cost from a character count (about four
characters per token). That number is your estimate, not a provider quote.
With no prices entered, Forge shows no cost.

Changing the conversion model does not change the Game Master used in play.

## Two machines on a home LAN

Optional environment variables let ordinary turns prefer one Ollama host
and fall back to another. See `deploy/saturday-multiverse.service.example`.
Manual mode, the default unless `SATURDAY_GM_AUTO=1`, keeps using the
single endpoint from Settings. The router never sends a turn to a public
provider on its own.

## Voice narration (planned)

The same adapter pattern will feed a text-to-speech pass for GM narration
(opt-in, off by default). The narration text is already isolated as a single string
per turn, so this needs no protocol changes.
