# `2-open-source-sdks/litellm-proxy/`

## What this shows

The LiteLLM proxy's built-in OpenTelemetry callback, end to end: the same
three-call support-ticket-triage scenario every app in this repo runs, but
sent as three `curl` requests against a running LiteLLM proxy container
instead of a Python script calling an SDK, with `litellm_settings.callbacks:
["otel"]` in `config.yaml` doing all the instrumentation — no code, no SDK
import, on either side of the request.

## Which setup this matches

Use this if you run the **LiteLLM proxy** (`litellm --config config.yaml`,
or its Docker image) as a gateway your application's HTTP client talks to,
and you want cost and token data in CACM without adding any tracing code
to the application making the requests. See the Harness docs' Cloud & AI
Cost Management → AI Traces → "OpenTelemetry" integration page for the
underlying product concepts this demo exercises.

If your application imports `litellm` directly (`litellm.completion()` /
`litellm.acompletion()`) rather than calling a separate proxy process, see
`1-harness-sdk/litellm/` instead — that's a different integration path
(the Harness SDK's instrumentor, not the proxy's own callback) with its
own tradeoffs; see that app's README "Which setup this matches" for the
distinction from this one.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and
  [Docker Compose](https://docs.docker.com/compose/)
- `curl`, [`jq`](https://jqlang.org/), and `openssl` (all three are
  present by default on the GitHub Actions runner this also runs under in
  CI; on macOS, `brew install jq` if you don't already have it)
- A real OpenAI API key — there's no local-Ollama-style zero-cost path for
  this app; `request.sh` talks to the proxy over HTTP, and the proxy needs
  a real upstream to call.
- **Local mode (default):** no Harness account, no Harness token needed —
  only the OpenAI key above.
- **Harness mode:** a Harness account ID and an ordinary personal/
  service-account token, sent as `x-harness-service-token` (see
  `docs/01-get-your-token.md`), in addition to the OpenAI key.

## Setup

```bash
cp .env.example .env
```

Put your OpenAI key in `.env` (`OPENAI_API_KEY=`) — required even for a
local-mode run. To also send traces to a real Harness account, uncomment
and fill in the three `OTEL_*` lines at the bottom of `.env` instead of
editing `docker-compose.yaml` or `config.yaml` — see `.env.example`'s
comments for exactly which three.

## Run

```bash
docker-compose up -d
./request.sh
```

Expected output (the severity label is deterministic — a forced tool call
at `temperature=0`; the summary and draft-reply wording vary slightly run
to run and are illustrative below):

```
--- Ticket ---
Subject: Checkout is broken for all EU customers
...

Call 1 -- classify severity (tool call)
Severity: critical

Call 2 -- summarize the ticket
Summary: EU customers are getting 500 errors at checkout since this morning's deploy, blocking revenue.

Call 3 -- draft a customer reply (uses calls 1+2 as context)
Draft reply:
Hi, we're aware that checkout is currently failing for customers in the EU
region and our team is treating this as critical. We're actively
investigating and will update you as soon as it's resolved. We're sorry
for the disruption.

Trace ID: <32 hex characters>
Open http://localhost:16686, service cacm-demo-litellm-proxy, and search by this trace ID -- see README.md "What to look for."
```

Local mode: open http://localhost:16686, find service
`cacm-demo-litellm-proxy`. Harness mode: see `docs/02-verify-traces.md`
for the Cost Explorer path.

Stop the proxy and its bundled Jaeger with `docker-compose down`.

## What to look for

**One trace, 21 spans** — verified against a real `docker-compose up`
run, not just read off the LiteLLM source. No wrapper span is needed the
way every `1-harness-sdk/*` app needs one: those apps' instrumentor opens
and closes each provider-call span entirely inside a single Python
function call, with nothing left "current" for the next call to attach
to, so `main.py` has to hold a manually-created parent span open across
all three. Here there's no Python process at all — `request.sh` sends the
same W3C `traceparent` header (one shared trace ID) on all three `curl`
calls, and the proxy attaches each request's own span tree to that
incoming trace context directly.

But "attaches each request's own span tree" is doing real work in that
sentence: the proxy's `otel` callback doesn't emit one span per request,
it emits **seven** — its own internal call path from HTTP handler down to
the raw provider response. All three requests produce an identical
7-span shape, so 3 × 7 = 21:

```
Received Proxy Server Request        <- server span, one per curl call
├── proxy_pre_call                    <- auth/data prep
├── router (async_get_available_deployment)
├── router (acompletion)
│   └── litellm_request               <- the gen_ai.* span, see below
│       └── raw_gen_ai_request        <- llm.openai.* span, see below
└── self (make_openai_chat_completion_request)
```

Only two of the seven matter for Cost Explorer:

| Span | Key attributes | Where it surfaces in Cost Explorer |
|---|---|---|
| `litellm_request` | `gen_ai.system=openai` (**not** `gen_ai.provider.name` — see callout below), `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.usage.total_tokens`, `gen_ai.cost.*` (LiteLLM computes its own cost estimate independently of Cost Explorer's) | the span Cost Explorer's `gen_ai.*` extraction reads |
| `raw_gen_ai_request` | `llm.openai.*`-prefixed (`llm.openai.model`, `llm.openai.usage`, `llm.openai.messages`, ...) — the OpenAI Python SDK's own response shape, dumped as-is, no `gen_ai.*` normalization | not read by Cost Explorer; useful for debugging the raw provider response, nothing more |

The other five spans per request (`Received Proxy Server Request`,
`proxy_pre_call`, both `router` spans, `self`) carry proxy-internal
attributes (`call_type`, `http.route`, `litellm.preprocessing.duration_ms`)
and no `gen_ai.*`/`llm.openai.*` data at all — they exist so you can see
where time went inside the proxy, not for cost attribution.

**`gen_ai.system`, not `gen_ai.provider.name`.** Every other app in this
repo's "What to look for" table documents `gen_ai.provider.name` because
that's what `harness-sdk`'s instrumentors emit. LiteLLM proxy's built-in
`otel` callback predates that semantic-convention name and still emits the
older `gen_ai.system` key for the same concept (which pricing table to
use). Functionally equivalent, and Cost Explorer accepts both key names (see
`docs/05-what-drives-cost.md`), so this doesn't affect cost attribution in
a real Harness account — but if you're grepping traces across apps in
this repo for provider identity, you need both key names; this is the one
app where `gen_ai.provider.name` won't be there.

Unlike every other app in this repo, there's no `custom.*` business
attribute here — that's `main.py`'s STEP 5, and this app has no `main.py`
to run it from. Anything you'd want attached to a span has to come from
the proxy's own request/response payload or from `config.yaml`, not from
inline code the way STEP 5 does it elsewhere. See "Adapt this to your app"
below for what LiteLLM's config format actually gives you here.

## How it works

The instrumenting configuration is one line, in `config.yaml`:

```yaml
litellm_settings:
  callbacks: ["otel"]
```

Turning this on makes the proxy log every request/response pair as a
7-span OTel span tree via LiteLLM's own OpenTelemetry integration — one of
those seven (`litellm_request`) carries `gen_ai.*` attributes — regardless
of which client sent the request or what language it's written in (see
"What to look for" for the full shape). Everything else in `config.yaml`
(`model_list`) is ordinary LiteLLM routing configuration, not
tracing-specific.

The rest of this app is plumbing, not instrumentation:
`docker-compose.yaml` runs the proxy container plus a bundled Jaeger; the
`OTEL_EXPORTER`/`OTEL_ENDPOINT`/`OTEL_HEADERS` environment variables (see
`.env.example`) tell that one callback where to send spans, the same way
every other family's `.env.example` configures its own exporter.

## Adapt this to your app

**Change freely:**
- `config.yaml`'s `model_list` — add your own models, point at any
  LiteLLM-supported provider string. Changing the provider likely means
  changing which credential env var this app needs; this demo only wires
  up `OPENAI_API_KEY`.
- The scenario in `request.sh` — replace the three calls with your own
  prompts.
- `OTEL_RESOURCE_ATTRIBUTES`'s `service.name` value in `.env`.

**Must not move:**
- `litellm_settings.callbacks: ["otel"]` in `config.yaml` — removing it is
  the same as removing `Agent().instrument()` from a `1-harness-sdk/*`
  app: every span this proxy would have emitted simply stops existing,
  with no error anywhere to explain why.
- The `extra_hosts: host.docker.internal:host-gateway` entry in
  `docker-compose.yaml` — harmless for a real run, but CI relies on it to
  reach its stubbed provider server; removing it breaks CI without
  affecting local or Harness-mode behavior at all, which makes it an easy
  thing to "clean up" by mistake.
- `env_file: .env` on the `litellm` service in `docker-compose.yaml`, and
  leaving `OPENAI_API_BASE` out of your own `.env` rather than setting it
  to an empty value — see `config.yaml`'s comment on `api_base` for why
  that distinction is what keeps a real run pointed at the real OpenAI
  API instead of an empty base URL.
