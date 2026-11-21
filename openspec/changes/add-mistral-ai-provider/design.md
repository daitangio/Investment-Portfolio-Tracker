# Design

## Context

The AI provider system in `backend/services/agents/_base.py` uses raw `httpx` calls (no SDKs) with per-provider runner functions (`_run_gemini_model`, `_run_openai_model`, `_run_claude_model`, etc.) dispatched through three entry points: `call_chat_llm` (advisor), `call_synthesis_llm` (analysis), and `call_cheap_llm` (specialist agents). Each provider is a value in the `Provider` Literal type, mirrored in the frontend `Provider` type in `useTrading.ts`.

Mistral's native endpoint `https://api.mistral.ai/v1/chat/completions` follows the same Chat Completions request/response structure as OpenAI: `Authorization: Bearer` auth, `messages[]` with role/content, `max_tokens`, `response_format: {"type": "json_object"}`, and response shape `choices[0].message.content`. This means the Mistral runners are near-copies of the OpenAI runners with a different base URL, model, and key.

## Goals / Non-Goals

**Goals:**
- Add `"mistral"` as a sixth provider value across all dispatch paths
- Reuse the OpenAI-compatible payload shape — no new HTTP client, no SDK
- Wire Mistral into all three LLM callers (chat, synthesis, cheap)
- Surface Mistral in all frontend provider selectors
- Configurable model via `MISTRAL_MODEL` env var

**Non-Goals:**
- Mistral-specific features (connectors, agents API, OCR) — out of scope
- Streaming via Mistral — the advisor streaming endpoint is separate and not affected
- Web search tool use (Claude-only feature) — Mistral calls will not use web search
- A Mistral availability/status endpoint (unlike Ollama/LM Studio, it's a cloud key — no local server to probe)

## Decisions

### Decision 1: Reuse OpenAI payload shape via dedicated runners (not parameterized base_url)
**Choice:** Add `_run_mistral_model()` and `_run_mistral_chat()` as standalone functions that mirror `_run_openai_model()` / `_run_openai_chat()` but with `https://api.mistral.ai/v1/chat/completions` as the URL.
**Rationale:** The existing codebase pattern is one runner per provider. A parameterized `base_url` on the OpenAI runner would be cleaner but would deviate from the established pattern and touch working OpenAI code. Dedicated functions are safer, more readable, and match the "less is more" project mantra by being explicit.
**Alternative considered:** Adding a `base_url` parameter to `_run_openai_model`/`_run_openai_chat` and reusing them for Mistral. Rejected because it modifies existing working code paths for OpenAI.

### Decision 2: Default models — `mistral-large-latest` for synthesis, `ministral-8b-latest` for cheap
**Choice:** `MISTRAL_MODEL` defaults to `mistral-large-latest` (best quality for synthesis/chat). Cheap specialist calls use `ministral-8b-latest` (fastest, cheapest Mistral model suitable for structured extraction).
**Rationale:** Matches the existing pattern where `agent_model_cheap` and `agent_model_synthesis` are separate. Mistral Large for synthesis quality, Ministrail 8B for cheap structured JSON extraction.
**Alternative considered:** Using `mistral-small-latest` for cheap calls. Ministrail 8B is smaller/faster and sufficient for the narrow JSON-extraction tasks the specialist agents perform.

### Decision 3: Mistral in cheap-LLM chain — position 3 (after Gemini free tier, after GPT-4o-mini, before synthesis fallback)
**Choice:** In `call_cheap_llm`, Mistral is tried after local providers, Gemini, and GPT-4o-mini, but before falling back to the user's synthesis provider.
**Rationale:** Mistral is a paid API, so it should rank after free options (local + Gemini free tier) but before the more expensive synthesis-provider fallback. This preserves the cost-optimization intent of `call_cheap_llm`.

### Decision 4: No `MISTRAL_BASE_URL` env var
**Choice:** Hardcode `https://api.mistral.ai/v1` as the base URL.
**Rationale:** The user confirmed they want the standard Mistral API (console.mistral.ai). Self-hosted/proxied Mistral is out of scope. Keeps config surface minimal.

### Decision 5: Frontend color — orange/red gradient for Mistral brand
**Choice:** `PROVIDER_CONFIG` entry: `mistral: { label: "Mistral", color: "bg-orange-600", dot: "bg-orange-400" }`.
**Rationale:** Mistral's brand color is orange. Distinct from existing provider colors (blue=Gemini, amber=Claude, green=OpenAI, violet=Ollama, teal=LM Studio).

## Risks / Trade-offs

- [Mistral rate limits are token-based and lower than OpenAI on free tier (~120 req/min)] → Error handler surfaces 429 with a clear "rate limited" message; user can upgrade plan.
- [JSON mode on Mistral requires the prompt to also instruct JSON output] → Existing agent prompts already include JSON instructions (shared across providers), so no change needed.
- [Mistral models may produce different quality analysis than Claude/Gemini] → Expected; user chooses provider explicitly. Analysis history tracks provider per result.
- [`response_format: json_object` on the native `/v1/` endpoint is confirmed supported per Mistral docs] → If it ever regresses, `extract_json()` still handles non-JSON-mode responses as fallback.

## Migration Plan

1. Add `MISTRAL_API_KEY=` (empty) to `.env` and `.env.example` — no migration needed, feature is opt-in.
2. Deploy backend changes — existing providers unaffected.
3. Deploy frontend changes — Mistral button appears but is only clickable when key is configured (backend returns clear error if not).
4. Rollback: remove `"mistral"` from the `Provider` Literal and frontend type — no data migration needed since `provider` is stored as a string in `AnalysisResult` and advisor conversations.

## Open Questions

- None — all decisions are resolved. Model names can be tuned later via env vars without code changes.
