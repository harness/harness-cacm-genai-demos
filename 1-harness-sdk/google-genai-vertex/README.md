# `1-harness-sdk/google-genai-vertex/`

## What this shows

The Harness OTel SDK's Google Gen AI instrumentation, end to end, against
the **Vertex AI** backend: a three-call support-ticket triage script built
on `harness-sdk[google-genai]` + the unified `google-genai` Python SDK
(`genai.Client(vertexai=True, ...)`), exporting OTLP/HTTP spans with token
counts to either a local Jaeger instance or Harness Cloud & AI Cost
Management (CACM).

## Which setup this matches

Use this if your app calls Gemini through Google's unified `google-genai`
SDK **in Vertex AI mode** — project + region, Application Default
Credentials, no API key — and you want cost and token data in CACM
without hand-rolling OpenTelemetry spans yourself. See the Harness docs'
Cloud & AI Cost Management → AI Traces → "Harness OTel SDK" integration
page for the underlying product concepts this demo exercises.

`google-genai` has a second, unrelated auth mode this app does **not**
use: the **Gemini Developer API**, `genai.Client(api_key=...)`, which
authenticates like every other provider in this repo (an API key, no
Google Cloud project). If that's what your app does, the instrumentation
this app exercises still applies — `gen_ai.provider.name` just comes out
`gcp.gemini` instead of `gcp.vertex_ai` (see "What to look for") — but no
demo for that mode exists in this repo yet.

If you don't call `google-genai` directly, see `1-harness-sdk/openai/`,
`1-harness-sdk/anthropic/`, `1-harness-sdk/litellm/`, or
`3-manual-instrumentation/python/` instead.

## Prerequisites

- Python >= 3.10
- [`uv`](https://docs.astral.sh/uv/)
- **Local mode (default):** nothing else. Unlike every other app in
  `1-harness-sdk/`, there is no provider API key anywhere in this app's
  `.env` — Vertex AI has no key-based auth mode, it authenticates via
  Application Default Credentials (ADC) — and there's no
  local-Ollama-style zero-cost path either. So the shipped `.env.example`
  points `GOOGLE_GENAI_BASE_URL` at
  [`mock-providers/mock_google_genai_server.py`](../../mock-providers/README.md)
  instead: a stub that answers the Vertex AI wire format with canned
  responses, and that main.py uses to skip ADC entirely (see its STEP 3
  comment). No Google Cloud project, no `gcloud auth
  application-default login`, no Harness account/token needed. To use
  real Vertex AI instead (real model output, real token counts), see
  "Setup" below.
- **Harness mode:** a Harness account ID and an ordinary personal/
  service-account token, sent natively as `x-harness-service-token` (see
  `docs/01-get-your-token.md`), in addition to real ADC credentials (the
  mock only proves the plumbing works — see `mock-providers/README.md`).

## Setup

```bash
cp .env.example .env
```

Local mode works with the file as shipped against the mock server (start
it first — see "Run" below). To use real Vertex AI instead, clear
`GOOGLE_GENAI_BASE_URL`, set `GOOGLE_CLOUD_PROJECT`, and run
`gcloud auth application-default login` once in the shell you'll run this
app from (or set `GOOGLE_APPLICATION_CREDENTIALS` to a service-account
key file). To also send traces to a real Harness account, edit two more
lines:

```bash
TRACE_TARGET=harness
HARNESS_ACCOUNT_ID=<your account id>
HARNESS_REPORTING_TOKEN=<your token>
```

Then install dependencies:

```bash
uv sync
```

## Run

In a separate terminal, leave this running (skip if using real ADC):

```bash
uv run ../../mock-providers/mock_google_genai_server.py
```

Then, in this terminal:

```bash
uv run main.py
```

Expected console output against real Vertex AI (the severity label is
deterministic — a forced function call at `temperature=0`; the summary and
draft-reply wording vary slightly run to run and are illustrative below):

```
--- Ticket ---
Subject: Checkout is broken for all EU customers
...

Severity: critical
Summary: EU customers are getting 500 errors at checkout since this morning's deploy, blocking revenue.

Draft reply:
Hi, we're aware that checkout is currently failing for customers in the EU
region and our team is treating this as critical. We're actively
investigating and will update you as soon as it's resolved. We're sorry
for the disruption.

[OTel] Flushing spans...
```

Against the default `mock-providers/` stub, the severity is still
`critical` (same forced function call), but the summary and draft reply
are both the mock's fixed line, `This is a stubbed CI response for the
demo scenario.` — expected; it proves the trace pipeline works, not the
model.

Local mode: open http://localhost:16686, find service
`cacm-demo-google-genai-vertex`.
Harness mode: see `docs/02-verify-traces.md` for the Cost Explorer path.

## What to look for

**One trace, four spans.** Unlike naively calling `generate_content()`
three times with nothing wrapping them — which would produce three
unrelated root traces, since google-genai's auto-instrumentation opens
and closes each call's span entirely inside that single call, with
nothing left "current" afterward for the next call to attach to —
`main.py` wraps all three calls in one manually-created parent span,
`support_ticket_triage`. That's what makes this a real single-trace
waterfall instead of three disconnected traces:

| Span | Key attributes | Where it surfaces in Cost Explorer |
|---|---|---|
| `support_ticket_triage` (parent, hand-created) | `custom.ticket_severity` from STEP 5 — no `gen_ai.*` attributes; this span isn't a provider call | AI Traces → Service Traces drawer, the trace root |
| `chat <model>` (classify severity) | `gen_ai.provider.name=gcp.vertex_ai`, `gen_ai.request.model`, `gen_ai.framework=google-genai`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens` | first child span in the waterfall |
| `chat <model>` (summarize) | same attribute set; larger `input_tokens` than the first call (same ticket text, different system instruction) | second child span in the waterfall |
| `chat <model>` (draft reply) | same attribute set; largest `input_tokens` — this call carries calls 1+2's output as context | third child span in the waterfall; token growth here is what drives most of this trace's cost |

The three `chat <model>` spans use the same naming convention as
`openai/` and `anthropic/`, unlike `litellm/`'s instrumentor-named
`litellm_request`.

**`custom.ticket_severity` lives on the parent span, not on any `chat`
span.** `set_span_attribute` only affects whichever span OpenTelemetry
considers "current" at the moment it's called — and each `chat` span is
already closed by the time its own `generate_content()` call returns, so
nothing set after any of them would land there. Placing the enrichment
call inside the `support_ticket_triage` `with` block (still open across
all three calls) is what makes it actually take effect; see `main.py`'s
STEP 4/STEP 5 comments.

**`gen_ai.provider.name` is backend-dependent, not model-dependent.** This
app's client is built with `vertexai=True`, so every span reads
`gcp.vertex_ai`. The same `google-genai` instrumentation, pointed at a
`genai.Client(api_key=...)` (Gemini Developer API) instead, would produce
`gcp.gemini` for the identical scenario and often the identical
underlying model — the attribute names the *backend*, not the model
family. There is no demo for that mode in this repo to cross-link yet.

**Two things this app's spans do *not* carry, unlike some other apps
here:** `gen_ai.usage.total_tokens` is never set by this instrumentor
(unlike `litellm/`'s spans), and `gen_ai.tool.definitions` (the declared
`classify_severity` schema) is not currently mapped from the request —
a known gap in `harness-sdk`'s `google-genai` instrumentation, not
something this app's code is missing.

## How it works

The instrumenting code is four lines, all in `main.py`:

```python
os.environ["HARNESS_ENABLE_AI_GOOGLE_GENAI"] = "true"   # STEP 1 — opt in
agent = Agent()                                          # STEP 2
agent.instrument()                                       # STEP 2 — before importing google.genai
from google import genai                                 # STEP 3 — only after instrument()
```

`Agent().instrument()` patches `google.genai.models.Models` so every
`generate_content()` call gets wrapped in a span automatically — the app
never sets a `gen_ai.*` attribute by hand. The three
`client.models.generate_content(...)` calls and the printed output are
ordinary application code beyond that.

One more piece of tracing-specific code, not part of the four lines
above: `main.py` opens its own span (`tracer.start_as_current_span(...)`)
around all three calls before making them. This isn't optional
boilerplate — without it, the three calls would land as three
disconnected root traces instead of one waterfall, since each
auto-created `chat` span's lifetime is scoped entirely to its own
`generate_content()` call (see "What to look for" above). It's also the
only reason STEP 5's `set_span_attribute` call has anywhere valid to
attach to.

## Adapt this to your app

**Change freely:**
- The scenario (`SUPPORT_TICKET`, the three calls, the tool schema) —
  replace with your own prompts and calls.
- `GOOGLE_GENAI_MODEL` — point at any Gemini model your project has
  access to.
- `GOOGLE_CLOUD_LOCATION` — any Vertex AI region your project supports.
- `HARNESS_SERVICE_NAME` — set to your actual service's name.
- The `custom.*` attribute name/value in STEP 5.

**Must not move:**
- The `agent.instrument()` call must stay before `from google import
  genai` (STEP 2 → STEP 3 ordering). This is the one rule that silently
  breaks tracing with no error if violated.
- `opentelemetry-util-genai` must stay an explicit dependency in
  `pyproject.toml`, not left to `harness-sdk[google-genai]`'s transitive
  resolution — see the comment there for why (it isn't pulled in
  transitively at all today).
- `vertexai=True` on the `genai.Client(...)` call — dropping it silently
  switches to the Gemini Developer API backend, which reads a completely
  different auth mode (`GOOGLE_API_KEY`) that this app's `.env.example`
  doesn't wire up.
- `HARNESS_ENABLE_CONSOLE_SPAN_EXPORTER` should stay `false` unless you
  specifically want stdout-only span dumps in place of real export.
- The `trace.get_tracer_provider().force_flush()` call at the end of
  STEP 6, for any script that exits shortly after its last GenAI call.
- The `support_ticket_triage` wrapper span around STEP 4's three calls,
  and STEP 5's `set_span_attribute` call staying inside that `with`
  block. Moving the calls outside it (or moving the enrichment call
  after it) brings back three disconnected traces and a
  `set_span_attribute` that silently does nothing — see "What to look
  for" above.
