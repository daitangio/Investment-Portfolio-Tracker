## General rules

- Think before acting. Read existing files before writing code.
- Be concise in output but thorough in reasoning.
- Prefer editing over rewriting whole files.
- Do not re-read files you have already read.
- Test your code before declaring done.
- No sycophantic openers or closing fluff.
- Keep solutions simple and direct.
- The overall project aims to be very compact (*less is more* mantra)
- Always ignore the var/ folder: nothing interesting is there.

- At the end of LOG.md, create a work in progress log, where you note what you already did, what is missing. Always update LOG.md at the end, following the template. Always include the name of the model used, version included.

## Project

InvestIQ — self-hosted portfolio tracker for equities, ETFs, and crypto, built with Australian investors in mind (AUD reporting base, ATO tax rules). Monorepo: FastAPI backend, Next.js 15 frontend, Docker Compose + Postgres/Redis. `taic/` is a git submodule (devcontainer + agent tooling) — do not modify it and ignore it.

## Commands

The root `Makefile` wraps everything; the root `.env` is the single source of config for both Makefile and Docker workflows (the Makefile `include`s it and exports its variables).

```bash
make serve          # start all Docker services (backend, frontend, postgres, redis, celery)
make restart        # restart backend + frontend containers
make rebuild        # rebuild images with cache
make logs           # tail all container logs (logs-backend / logs-frontend)
make stop           # stop all services

make infra          # start only Postgres + Redis (for local development)
make dev-local      # run backend + frontend locally against Dockerized Postgres/Redis
make install        # create repo-root .venv with backend deps + npm install frontend

make test           # backend tests: cd backend && ../.venv/bin/python -m pytest tests -q
make type-check     # frontend: tsc --noEmit
make repair-assets  # dry-run repair of ASX holdings stored as USD (APPLY=1 to commit)
make push MSG="..." # git pull --rebase, add -A, commit, push (repo convention for committing)
```

Run a single backend test:

```bash
cd backend && ../.venv/bin/python -m pytest tests/test_portfolio_currency.py::TestClassName::test_name -q
```

Backend tests are plain `unittest` + `unittest.mock` with fake DB session objects (`_FakeDb` etc. inline in test files) — they need no live database. Seed scripts in `scripts/` and `backend/scripts/` populate dev data.

Local ports: frontend 3000, backend 8010 (API docs at `http://localhost:8010/docs`), Postgres 15432, Redis 16379, Flower 5555. Container-to-container traffic uses standard internal ports; the host ports only avoid clashes.

## Architecture

### Backend (`backend/`)

Layered: `routers/` (thin HTTP layer, wired in `main.py` under `/api/v1/*` — except `bank_import` which has no prefix) → `services/` (business logic) → `shared/` (`models.py`, `auth.py`, `cache.py`, `assets.py`). The primary `database.py` (async engine + `get_db` dependency that commits on success and rolls back on exception) is at backend root. **Note**: App startup runs `Base.metadata.create_all` via lifespan in `main.py` — disable or comment this in production to avoid conflicts with Alembic (`backend/alembic/`, async `env.py`) migrations.
- `config.py`: pydantic-settings `Settings` from env vars; holds AU localization defaults (default currency AUD, tax year starts July 1, CGT discount rate — 0.50 individuals / 0.3333 SMSF).
- **Portfolio engine** (`services/portfolio_engine.py`) and **analytics engine** (`services/analytics_engine.py`) are pure computation with injected data — FIFO cost basis, per-transaction FX, realized/unrealized P&L, drawdowns, benchmark comparison.
- **Currency**: everything converts through an AUD pivot. The `FXService` class in `services/fx_service.py` handles all currency conversion. It uses Yahoo Finance as primary FX source with RBA f11.1 XLS/fallback API as secondary. Key details:
  - **RBA Series Dictionary** (`RBA_SERIES_ID`): maps major currencies (USD, EUR, GBP, JPY, CNY, CAD, HKD, SGD, NZD) to Reserve Bank of Australia series IDs for fallback FX rate fetching
  - **Stablecoin Normalization**: USDT, USDC, DAI, BUSD are automatically mapped to USD for FX conversion
  - **Default Currency**: AUD (set in `config.py`) as the reporting base for Australian tax compliance
  - **Per-Entity Currency Fields**: Asset, Transaction, Account, and User models each store their own currency (3-letter ISO codes)
  - **AUD Pivot**: All conversions pass through AUD; `fx_rate_to_aud` is mandatory on transactions for ATO CGT calculations
  - **Provider Chain**: ASX symbols resolve via `.AX` suffix in `market_data_service.py` with fallback chain (Yahoo → CoinGecko → Polygon)
- **Tax**: `services/ato_tax_engine.py` implements AU financial-year rules (CGT discount, franking credits); `TaxYearSettings` stores per-FY reconciliation adjustments between broker feeds and annual tax statements.
- **AI**: `services/agents/` — a multi-agent pipeline (technical / fundamental / news specialists + synthesis). `_base.py` provides the provider abstraction (claude / openai / gemini / ollama / lmstudio), pydantic output models, and cheap-LLM auto-selection.
- **Workers**: Celery (`workers/celery_app.py`) with tasks in `workers/tasks/` across queues `high_priority` / `default` / `low_priority`; Redis is the broker.

### Frontend (`frontend/`)

Next.js 15 App Router, TypeScript, Tailwind, TanStack Query, Recharts.

- `app/dashboard/` has nested routes for: advisor, analysis, import, markets, tax, transactions, watchlist. The main dashboard view (`page.tsx`) displays analytics and portfolio overview.
- **Auth**: JWT stored in localStorage (`access_token`), injected by the axios interceptor in `lib/api/client.ts`; 401/403 redirects to `/login`. Display currency persists as `display_currency` in localStorage (`lib/context/CurrencyContext.tsx`, defaults AUD) — **currently limited to "AUD" | "USD" types**.
- Data fetching lives in TanStack Query hooks in `lib/hooks/` (one per domain, e.g. `usePortfolio.ts`, `useAnalytics.ts`).

## Workflow conventions

- **OpenSpec spec-driven workflow**: proposals, deltas, and tasks live in `openspec/`; use the `openspec-*` skills (propose → apply → archive) for changes. `openspec/specs/` is currently empty and `add-eur-currency-support` is the active change (removing binary AUD/USD assumptions). `.claude/skills/` and `.vibe/skills/` mirror each other for cross-harness compatibility.
- **From `AGENTS.md`** (repo-wide agent contract):
  - Keep the project compact — "less is more"; prefer editing over rewriting; read files before changing them.
  - Ignore the `var/` folder everywhere.
  - Prefix shell commands with `rtk` (token-optimized output filter; `rtk proxy <cmd>` runs raw without filtering, `rtk gain` shows savings).
  - At the end of each work session, append a WIP entry to `LOG.md` (currently empty; entries follow the format `- YYYY-MM-DD: what was done, what is missing. (model, version)`).

# RTK - Rust Token Killer (Codex CLI)

**Usage**: Token-optimized CLI proxy for shell commands.

## Rule

Always prefix shell commands with `rtk`.

Examples:

```bash
rtk git status
rtk cargo test
rtk npm run build
rtk pytest -q
```

## Meta Commands

```bash
rtk gain            # Token savings analytics
rtk gain --history  # Recent command savings history
rtk proxy <cmd>     # Run raw command without filtering
```

## Verification

```bash
rtk --version
rtk gain
which rtk
```
