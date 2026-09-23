# Run locally first

Every demo in this repo defaults to `TRACE_TARGET=local` — you can see a
full GenAI trace with token counts before creating a Harness account,
generating a token, or spending anything with a provider. This page is
the fastest path to that first trace.

## 1. Start the local collector

From the repo root:

```bash
cd local-collector
docker-compose up -d
```

This starts a single-container Jaeger with its UI on
`http://localhost:16686` and an OTLP/HTTP receiver on port `4418` (not the
OTel default `4318` — see `local-collector/README.md` if you're curious
why). Every demo's `.env.example` already points `LOCAL_OTLP_ENDPOINT` at
`4418` for you.

[`2-open-source-sdks/litellm-proxy/`](../2-open-source-sdks/litellm-proxy/README.md)
is the one exception: it bundles its own Jaeger in its own
`docker-compose.yaml` rather than using this one, so it stays copyable out
of this repo in isolation like every other app folder — you don't need to
start `local-collector/` for it at all.

## 2. Pick a demo and follow its own README

Every demo's `README.md` has "Prerequisites," "Setup," and "Run" sections
specific to that app. In broad strokes, for any Family 1 (`1-harness-sdk/`)
or Family 3 (`3-manual-instrumentation/`) Python app:

```bash
cd 1-harness-sdk/openai        # or whichever demo you picked
cp .env.example .env           # local mode works as shipped, nothing to edit
uv sync
uv run main.py
```

[`2-open-source-sdks/litellm-proxy/`](../2-open-source-sdks/litellm-proxy/README.md)
doesn't follow this shape at all — no `main.py`, no `uv`; it's
`docker-compose up -d` followed by `./request.sh`. See its own README's
"Run" section rather than the pattern above.

`1-harness-sdk/openai/` ships pointed at a local [Ollama](https://ollama.com)
instance by default, so it needs zero OpenAI account or API key in
local mode — just `ollama run llama3.2:1b` running first. Every other
Family 1 app is the exception: there's no equivalent free local model, so
`1-harness-sdk/anthropic/` and [`1-harness-sdk/litellm/`](../1-harness-sdk/litellm/README.md)
(which routes through Anthropic by default) both need `ANTHROPIC_API_KEY`
even in local mode, and [`1-harness-sdk/google-genai-vertex/`](../1-harness-sdk/google-genai-vertex/README.md)
needs Application Default Credentials instead — Vertex AI has no
key-based or free-tier local path at all. Each app's own `README.md`
"Prerequisites" section says which applies.

## 3. Look at the trace

Open `http://localhost:16686`, and select the service name the demo
printed (e.g. `cacm-demo-openai`) from the Jaeger UI's service dropdown.
Every `1-harness-sdk/*` app produces **one trace** with a parent span plus
one child span per provider call; `3-manual-instrumentation/python/`
produces **three separate traces**, one span each, since nothing there
propagates a shared trace context across its three hand-rolled spans. See
each app's "What to look for" section for the exact span shape and
attributes.

Jaeger doesn't compute a dollar cost the way CACM's Cost Explorer does —
local mode proves the instrumentation and the attributes are correct, not
the pricing math. For that, see `02-verify-traces.md` once you're ready to
point a demo at a real Harness account.

## Going from here to a real Harness account

Nothing about switching later requires re-running setup from scratch.
Every demo's `.env` has exactly two lines to change:

```bash
TRACE_TARGET=harness
HARNESS_ACCOUNT_ID=<your account id>
HARNESS_REPORTING_TOKEN=<your token>
```

See `01-get-your-token.md` for how to get those two values.
