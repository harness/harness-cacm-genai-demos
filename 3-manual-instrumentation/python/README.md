# `3-manual-instrumentation/python/`

## What this shows

Cost-attributed GenAI tracing with **no SDK and no auto-instrumentor at
all**: a three-call support-ticket triage script that calls the OpenAI
Python SDK directly, wraps each call in a hand-rolled OpenTelemetry span
using the raw `opentelemetry-sdk` + `opentelemetry-exporter-otlp`
packages, and sets every `gen_ai.*` attribute Harness Cloud & AI Cost
Management (CACM) needs by hand.

## Which setup this matches

Use this if you can't or don't want to add `harness-sdk` or any
`opentelemetry-instrumentation-*` package to your app — e.g. your
provider has no OTel instrumentor yet, you're calling a provider through
a thin internal wrapper an instrumentor can't see into, or you just want
full control over exactly what's on the span. See the Harness docs'
Cloud & AI Cost Management → AI Traces → "Manual instrumentation"
integration page for the underlying product concepts this demo
exercises.

If you do call a directly-supported provider SDK (OpenAI, Anthropic, …)
and don't need that control, `1-harness-sdk/openai/` or
`1-harness-sdk/anthropic/` get you the same result with far less code.

## Prerequisites

- Python >= 3.10
- [`uv`](https://docs.astral.sh/uv/)
- **Local mode (default):** nothing else. The shipped `.env.example`
  points the OpenAI client at
  [`mock-providers/mock_openai_server.py`](../../mock-providers/README.md),
  so no OpenAI account and no Harness account/token are needed — start it
  in a separate terminal
  (`uv run ../../mock-providers/mock_openai_server.py`) before "Run"
  below; canned responses, not real model output. Two alternatives, both
  documented as commented-out blocks in `.env.example`: point
  `OPENAI_BASE_URL` at a local [Ollama](https://ollama.com) instance
  (`ollama run llama3.2:1b`) for real model output with still no OpenAI
  account, or use a real OpenAI API key for the real API.
- **Harness mode:** an OpenAI API key (or continue pointing at the mock
  or Ollama — the provider and the trace target are independent
  switches), plus a Harness account ID and an ordinary personal/
  service-account token, sent as `x-harness-service-token` (see
  `docs/01-get-your-token.md`).

## Setup

```bash
cp .env.example .env
```

Local mode works with the file as shipped against the mock server (start
it first — see "Run" below). To use a local Ollama instance instead (real
model output, still zero OpenAI account) or a real OpenAI API key, comment
out the shipped `OPENAI_*` lines in `.env` and uncomment the alternative
block you want — see `.env.example`'s comments for exactly which lines.

To send traces to a real Harness account instead, edit two lines in `.env`:

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

In a separate terminal, leave this running (skip if using Ollama or a real OPENAI_API_KEY):

```bash
uv run ../../mock-providers/mock_openai_server.py
```

Then, in this terminal:

```bash
uv run main.py
```

Expected console output (the severity label is deterministic — a forced
tool call at `temperature=0`; the summary and draft-reply wording vary by
model and are illustrative below):

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

Local mode: open http://localhost:16686, find service
`cacm-demo-manual-python`. Harness mode: see `docs/02-verify-traces.md`
for the Cost Explorer path.

## What to look for

Three spans, one per call, each named `chat <model>` (e.g. `chat
llama3.2:1b` or `chat gpt-4o-mini`), each carrying the attribute set
below because `main.py`'s `start_chat_span()`/`record_usage()` set it
explicitly — nothing here is auto-captured.

**Required attributes** — the exact set the public manual-instrumentation
page documents, and what silently breaks in Cost Explorer if you drop one:

| Attribute | Set in `main.py` | What breaks if omitted |
|---|---|---|
| `gen_ai.provider.name` | `start_chat_span()`, before the call | The span still ingests, but Cost Explorer can't price it — cost depends on provider-specific rate tables, so an unattributed span shows token counts with no dollar cost. |
| `gen_ai.request.model` | `start_chat_span()`, before the call | Same failure mode as above, one level more specific: without the model name, Cost Explorer can't pick the right rate *within* a provider (e.g. `gpt-4o-mini` vs. `gpt-4o` pricing differs by ~20x). |
| `gen_ai.usage.input_tokens` | `record_usage()`, after the call returns | Cost for this span computes as zero — there's no token count to multiply a rate by. The span still appears in the waterfall, but contributes nothing to the trace's total. |
| `gen_ai.usage.output_tokens` | `record_usage()`, after the call returns | Same as `input_tokens`, but for the (usually pricier) completion side — omitting just this one still under-costs the span, not zeroes it, since input-token cost alone still applies. |
| `gen_ai.agent.name` | `start_chat_span()`, before the call | The span still gets a dollar cost, but that cost can't be rolled up under an agent in Cost Explorer's per-agent breakdown — it only shows up in the raw per-service total. |

| Span | Attributes beyond the required set | Where it surfaces in Cost Explorer |
|---|---|---|
| `chat <model>` (classify severity) | — | AI Traces → Service Traces drawer, first span in the waterfall |
| `chat <model>` (summarize) | — ; larger `input_tokens` than the first call (same ticket text, different system prompt) | second span in the waterfall |
| `chat <model>` (draft reply) | `custom.ticket_severity` from STEP 5; largest `input_tokens` — this call carries calls 1+2's output as context | third span in the waterfall; token growth here is what drives most of this trace's cost |

`gen_ai.usage.input_tokens` here is a straight passthrough of the OpenAI
API's own `prompt_tokens` — same cache-inclusion semantics as
`1-harness-sdk/openai/`, since both apps read it off the same field on
the same SDK's response object. The difference between the two apps is
entirely in *how* the attribute lands on the span, not what value it
holds.

## How it works

There's no single "instrumenting call" here the way `agent.instrument()`
is for the Harness SDK apps — manual instrumentation *is* writing this
code. The parts that matter, all in `main.py`:

```python
provider = TracerProvider(resource=resource)                 # STEP 2
provider.add_span_processor(BatchSpanProcessor(exporter))     # STEP 2
trace.set_tracer_provider(provider)                            # STEP 2

span = tracer.start_span(f"chat {model}", kind=SpanKind.CLIENT)  # STEP 4
span.set_attribute("gen_ai.provider.name", "openai")              # STEP 4
span.set_attribute("gen_ai.request.model", model)                  # STEP 4
span.set_attribute("gen_ai.agent.name", AGENT_NAME)                  # STEP 4
# ... call the API ...
span.set_attribute("gen_ai.usage.input_tokens", usage.prompt_tokens)   # STEP 4
span.set_attribute("gen_ai.usage.output_tokens", usage.completion_tokens)  # STEP 4
span.end()                                                              # STEP 4
```

Everything else in `main.py` — the ticket, the three
`client.chat.completions.create(...)` calls, the printed output — is
ordinary application code with nothing GenAI-tracing-specific about it,
same as every other app in this repo.

## Adapt this to your app

**Change freely:**
- The scenario (`SUPPORT_TICKET`, the three calls, the tool schema) —
  replace with your own prompts and calls.
- The provider client — swap `openai.OpenAI(...)` for any HTTP-based
  provider client; `start_chat_span()`/`record_usage()` don't care what
  made the call, only that a response with token counts comes back.
- `OPENAI_MODEL` / `OPENAI_BASE_URL` — point at any OpenAI-API-compatible
  endpoint.
- `AGENT_NAME` and the `custom.*` attribute name/value in STEP 5.

**Must not move:**
- All five attributes in the required-attribute table above, set on
  every span — this is the one rule that silently under-costs or
  zero-costs a span with no error if violated.
- `custom.ticket_severity` must be set before `span.end()`, inside the
  same `try` block that produced the value — `set_attribute()` on an
  already-ended span is a silent no-op.
- The `try`/`except`/`finally: span.end()` shape around each call — a
  hand-rolled span that's never explicitly ended never exports.
- The `trace.get_tracer_provider().force_flush()` call at the end of
  STEP 6, for any script that exits shortly after its last GenAI call.
