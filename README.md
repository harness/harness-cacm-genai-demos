# harness-cacm-genai-demos

Copy-paste demo applications that show every supported way of sending GenAI
traces into Harness Cloud & AI Cost Management (CACM). Pick the row below
that matches your stack, copy that one folder out of this repo, run two
commands, and you'll see a GenAI trace — with token counts and cost
attribution — in a local Jaeger UI or in CACM's Cost Explorer.

There is no shared code between demos. Each folder is self-contained and
safe to copy in isolation; you don't need the rest of this repository.

## Pick your stack

| Family | Folder | Stack | Status |
|---|---|---|---|
| Harness SDK | [`1-harness-sdk/openai/`](1-harness-sdk/openai/README.md) | `harness-sdk` + OpenAI | Ready |
| Harness SDK | [`1-harness-sdk/anthropic/`](1-harness-sdk/anthropic/README.md) | `harness-sdk` + Anthropic | Ready |
| Harness SDK | [`1-harness-sdk/litellm/`](1-harness-sdk/litellm/README.md) | `harness-sdk` + LiteLLM (direct import) | Ready |
| Harness SDK | [`1-harness-sdk/google-genai-vertex/`](1-harness-sdk/google-genai-vertex/README.md) | `harness-sdk` + Google GenAI (Vertex) | Ready |
| Harness SDK | `1-harness-sdk/fastapi-service/` | `harness-sdk` in a long-lived FastAPI service | Planned |
| Open-source SDKs | [`2-open-source-sdks/litellm-proxy/`](2-open-source-sdks/litellm-proxy/README.md) | LiteLLM proxy, OTel callback | Ready |
| Open-source SDKs | `2-open-source-sdks/claude-code/` | Claude Code native OTel export | Planned |
| Open-source SDKs | `2-open-source-sdks/langchain-langgraph/` | LangChain / LangGraph | Parked — no cost data yet |
| Open-source SDKs | `2-open-source-sdks/openai-agents/` | OpenAI Agents SDK | Parked — no cost data yet |
| Open-source SDKs | `2-open-source-sdks/llamaindex/` | LlamaIndex | Parked — no cost data yet |
| Open-source SDKs | `2-open-source-sdks/google-adk/` | Google Agent Development Kit | Parked — no cost data yet |
| Manual instrumentation | [`3-manual-instrumentation/python/`](3-manual-instrumentation/python/README.md) | Raw OpenTelemetry SDK, Python | Ready |
| Manual instrumentation | `3-manual-instrumentation/go/` | Raw OpenTelemetry SDK, Go | Planned |

"Parked" rows are fully documented but don't yet carry cost data end-to-end;
see each family's own `README.md` once it lands for the current caveat.

## Setup

Every demo defaults to sending traces to a local Jaeger instance — no
Harness account, no API token, no live spend needed to try it. Start the
shared local collector once from the repo root:

```bash
cd local-collector
docker-compose up -d
```

See `local-collector/README.md` for why the ports aren't the OTel
defaults. To send traces to your real Harness account instead, see
`docs/01-get-your-token.md`; each demo's `.env.example` documents the two
lines you need to change.

Most demos also need a real provider account. None of them require one by
default: every `1-harness-sdk/`/`3-manual-instrumentation/python/`/
`2-open-source-sdks/litellm-proxy/` app ships pointed at
[`mock-providers/`](mock-providers/README.md)'s stub servers instead —
`1-harness-sdk/openai/` and `3-manual-instrumentation/python/` also
support a local Ollama instance as a real-model-output alternative, still
with zero provider credentials. See `docs/03-run-locally-first.md` and
each demo's own `README.md` "Prerequisites" for which paths apply.

## Usage

Copy the one folder matching your stack from the table above out of this
repo (or just `cd` into it here) and follow its own `README.md` — every
demo is self-contained: `cp .env.example .env`, edit two lines, `uv sync`,
then run. View traces at http://localhost:16686 in local mode, or in
CACM's Cost Explorer once pointed at a real account.

## Documentation

Deeper walkthroughs that apply across every demo live in
[`docs/`](docs/):

- [`docs/01-get-your-token.md`](docs/01-get-your-token.md) — service
  account → API key → token, account ID, cluster host
- [`docs/02-verify-traces.md`](docs/02-verify-traces.md) — confirming
  traces landed in Cost Explorer
- [`docs/03-run-locally-first.md`](docs/03-run-locally-first.md) — the
  Jaeger path, no Harness account needed
- [`docs/04-troubleshooting.md`](docs/04-troubleshooting.md) — a
  symptom-keyed "no spans appeared" decision tree
- [`docs/05-what-drives-cost.md`](docs/05-what-drives-cost.md) — which
  `gen_ai.*` attributes cost is computed from

## Contributing

See `CONTRIBUTING.md` for the file contract every demo folder follows, and
`AGENTS.md` if you're an AI coding agent adding one. All contributors must
sign the Contributor License Agreement — see `CLA.md` — before a PR can
be merged.

## License

Apache-2.0 — see `LICENSE.md`. Third-party attributions are in
`NOTICE.md`.
