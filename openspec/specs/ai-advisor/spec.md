# AI Advisor Specification

## Purpose

The AI advisor and multi-agent analysis pipeline support multiple LLM providers so users can choose the model that best fits their needs, budget, and privacy preferences. This capability covers provider selection, LLM dispatch, API key/model configuration, and the frontend provider UI across the advisor chat and asset analysis views.

## Requirements

### Requirement: Mistral as a selectable AI provider
The system SHALL accept `"mistral"` as a valid provider value in all provider dispatch paths: advisor chat (`call_chat_llm`), analysis synthesis (`call_synthesis_llm`), and specialist-agent cheap calls (`call_cheap_llm`).

#### Scenario: Advisor chat with Mistral provider
- **WHEN** a user sends a chat message with `provider: "mistral"` and a valid `MISTRAL_API_KEY` is configured
- **THEN** the advisor responds using the Mistral model via `https://api.mistral.ai/v1/chat/completions`

#### Scenario: Analysis synthesis with Mistral provider
- **WHEN** a user runs asset analysis with `provider: "mistral"`
- **THEN** the synthesis agent calls Mistral's chat completions endpoint and returns a parsed analysis result with `_provider: "mistral"`

#### Scenario: Mistral in cheap-LLM fallback chain
- **WHEN** `call_cheap_llm` is invoked and neither local (Ollama/LM Studio) nor free-tier (Gemini) providers succeed, but a valid Mistral key is present
- **THEN** the specialist agent call falls back to Mistral's `ministral-8b-latest` (or configured cheap model)

### Requirement: Mistral API key configuration
The system SHALL read the Mistral API key from the `MISTRAL_API_KEY` environment variable and the synthesis model from `MISTRAL_MODEL` (default `mistral-large-latest`).

#### Scenario: Key not configured
- **WHEN** a Mistral provider call is attempted but `MISTRAL_API_KEY` is empty or a placeholder
- **THEN** the system raises a clear error: "Mistral API key not configured"

#### Scenario: Key configured via env
- **WHEN** `MISTRAL_API_KEY` is set in `.env` and the backend starts
- **THEN** `settings.mistral_api_key` holds the secret value and Mistral calls authenticate with `Authorization: Bearer <key>`

### Requirement: Mistral structured JSON output
The system SHALL request JSON-mode output from Mistral using `response_format: {"type": "json_object"}` for specialist agents, matching the existing OpenAI-compatible payload shape.

#### Scenario: Specialist agent gets valid JSON
- **WHEN** a specialist agent (technical/news/fundamental) calls Mistral with `response_format: {"type": "json_object"}`
- **THEN** the response `choices[0].message.content` contains parseable JSON matching the agent's pydantic output model

### Requirement: Frontend provider selector includes Mistral
The system SHALL display a "Mistral" button in the advisor chat provider selector and the analysis page provider selector, with a distinct color badge.

#### Scenario: Advisor page shows Mistral option
- **WHEN** the advisor page renders the provider selector
- **THEN** a "Mistral" button appears alongside Gemini, Claude, GPT-4o, Ollama, and LM Studio

#### Scenario: Analysis page shows Mistral option
- **WHEN** the analysis detail page renders the provider selector
- **THEN** a "Mistral" button appears in the cloud-provider group

#### Scenario: Analysis history labels Mistral
- **WHEN** an analysis result with `provider: "mistral"` appears in the history page
- **THEN** the provider column displays "Mistral"

### Requirement: Mistral error handling
The system SHALL surface meaningful error messages for common Mistral API failures (401 auth, 429 rate limit, 5xx server errors).

#### Scenario: Invalid API key
- **WHEN** Mistral returns HTTP 401
- **THEN** the error message indicates the API key is invalid or missing

#### Scenario: Rate limited
- **WHEN** Mistral returns HTTP 429
- **THEN** the error message indicates rate limiting and suggests retrying or upgrading the plan
