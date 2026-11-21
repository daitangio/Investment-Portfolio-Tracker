# Proposal

## Why

The AI Advisor and multi-agent analysis pipeline currently support five providers (Claude, OpenAI, Gemini, Ollama, LM Studio) but not Mistral — a major European LLM provider whose models (Mistral Large, Mistral Small, Ministrail) are competitive for portfolio analysis and chat. Users who hold a Mistral API key (from console.mistral.ai) cannot use it. Mistral's native `/v1/chat/completions` endpoint follows the same request/response structure as OpenAI, so integration is low-cost: the existing httpx-based runners can be reused with a different base URL and model name.

## What Changes

- Add `"mistral"` as a valid `Provider` value across the backend (`_base.py` Literal, `call_chat_llm`, `call_synthesis_llm`, `call_cheap_llm`) and frontend (`Provider` type in `useTrading.ts`).
- Add `_run_mistral_model()` and `_run_mistral_chat()` runners in `backend/services/agents/_base.py` that call `https://api.mistral.ai/v1/chat/completions` with `Authorization: Bearer $MISTRAL_API_KEY`. Both reuse the OpenAI-compatible payload shape (messages, max_tokens, response_format json_object, choices[0].message.content).
- Add `mistral_api_key: SecretStr` and `mistral_model: str = "mistral-large-latest"` settings in `backend/config.py`.
- Add `MISTRAL_API_KEY` to `.env` and `.env.example`.
- Add Mistral to the `Literal` provider union in `backend/routers/trading.py` (`AnalyzeRequest`) and update the comment in `backend/routers/advisor.py` (`ChatRequest`).
- Add Mistral to the cheap-LLM fallback chain in `call_cheap_llm()` — after Gemini and GPT-4o-mini, before the synthesis-provider fallback.
- Frontend: add `mistral` to `PROVIDER_CONFIG` in `advisor/page.tsx`, to the provider selector buttons in `analysis/[symbol]/page.tsx`, to the provider badge colors, and to `PROVIDER_LABEL` in `analysis/history/page.tsx`.
- No new status endpoint needed (cloud API key, not a local server like Ollama/LM Studio).

## Capabilities

### New Capabilities
- `ai-advisor`: The AI advisor and multi-agent analysis pipeline provider system. Covers provider selection, LLM dispatch, configuration of API keys/models, and frontend provider UI. This change adds Mistral as a sixth provider to this capability.

### Modified Capabilities
- (none — no existing spec covers AI providers; `ai-advisor` is new)

## Impact

- `backend/config.py` — new settings fields (`mistral_api_key`, `mistral_model`)
- `backend/services/agents/_base.py` — new `Provider` literal value, two new runner functions, three dispatcher branches
- `backend/routers/trading.py` — `AnalyzeRequest.provider` Literal extended
- `backend/routers/advisor.py` — comment update
- `backend/services/ai_advisor_service.py` — comment update
- `frontend/src/lib/hooks/useTrading.ts` — `Provider` type extended
- `frontend/src/app/dashboard/advisor/page.tsx` — `PROVIDER_CONFIG` entry
- `frontend/src/app/dashboard/analysis/[symbol]/page.tsx` — provider button + badge color
- `frontend/src/app/dashboard/analysis/history/page.tsx` — `PROVIDER_LABEL` entry
- `.env`, `.env.example` — `MISTRAL_API_KEY`
