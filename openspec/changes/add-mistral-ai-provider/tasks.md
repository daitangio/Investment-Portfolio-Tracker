# Tasks

## 1. Backend Configuration

- [x] 1.1 Add `mistral_api_key: SecretStr = SecretStr("")` and `mistral_model: str = "mistral-large-latest"` to `backend/config.py` in the AI section — verify with `cd backend && ../.venv/bin/python -c "from config import get_settings; s = get_settings(); print(s.mistral_model)"`
- [x] 1.2 Add `MISTRAL_API_KEY=` to `.env` and `MISTRAL_API_KEY=your-mistral-api-key` (with comment) to `.env.example` — verify with `rtk grep MISTRAL .env .env.example`

## 2. Backend LLM Runners (_base.py)

- [x] 2.1 Add `"mistral"` to the `Provider` Literal type at `backend/services/agents/_base.py:30` — verify with `rtk grep 'Provider = Literal' backend/services/agents/_base.py`
- [x] 2.2 Add `_mistral_error(resp)` error formatter after `_gemini_error` — verify function exists
- [x] 2.3 Add `_run_mistral_model(system, user_msg, model, api_key, max_tokens)` that POSTs to `https://api.mistral.ai/v1/chat/completions` with `response_format: {"type": "json_object"}`, Bearer auth, and parses `choices[0].message.content` via `extract_json()` — verify with `cd backend && ../.venv/bin/python -c "from services.agents._base import _run_mistral_model; print('ok')"`
- [x] 2.4 Add `_run_mistral_chat(messages, system, model, api_key, max_tokens)` for multi-turn chat — verify import succeeds
- [x] 2.5 Add `elif provider == "mistral":` branch in `call_chat_llm()` — verify with grep
- [x] 2.6 Add `elif provider == "mistral":` branch in `call_synthesis_llm()` — verify with grep
- [x] 2.7 Add Mistral fallback in `call_cheap_llm()` after the GPT-4o-mini block (position 3 in chain, before synthesis fallback) using `ministral-8b-latest` — verify with grep

## 3. Backend API Schemas

- [x] 3.1 Add `"mistral"` to the `Literal` in `AnalyzeRequest.provider` at `backend/routers/trading.py:55` — verify with `rtk grep 'provider: Literal' backend/routers/trading.py`
- [x] 3.2 Update the `provider` comment in `ChatRequest` at `backend/routers/advisor.py` to include `"mistral"` — verify with grep
- [x] 3.3 Update the `Provider` comment in `backend/services/ai_advisor_service.py:27` — verify with grep

## 4. Frontend Provider Type and UI

- [x] 4.1 Add `"mistral"` to the `Provider` type at `frontend/src/lib/hooks/useTrading.ts:6` — verify with `make type-check`
- [x] 4.2 Add `mistral: { label: "Mistral", color: "bg-orange-600", dot: "bg-orange-400" }` to `PROVIDER_CONFIG` in `frontend/src/app/dashboard/advisor/page.tsx` — verify with `make type-check`
- [x] 4.3 Add Mistral button to the cloud-provider group in `frontend/src/app/dashboard/analysis/[symbol]/page.tsx` provider selector (after OpenAI button) — verify with `make type-check`
- [x] 4.4 Add Mistral badge color branch in `analysis/[symbol]/page.tsx` provider badge (line ~746) — orange theme — verify with `make type-check`
- [x] 4.5 Add `mistral: "Mistral"` to `PROVIDER_LABEL` in `frontend/src/app/dashboard/analysis/history/page.tsx:55` — verify with `make type-check`

## 5. Verification

- [x] 5.1 Run backend tests: `make test` — verify no regressions
- [x] 5.2 Run frontend type check: `make type-check` — verify zero errors
- [x] 5.3 Verify OpenSpec validation: `openspec validate add-mistral-ai-provider --strict`
