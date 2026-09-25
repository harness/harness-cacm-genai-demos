# `1-harness-sdk/anthropic/`

## What this shows

The Harness OTel SDK's Anthropic GenAI instrumentation, end to end: a
three-call support-ticket triage script built on `harness-sdk[anthropic]` +
the Anthropic Python SDK, exporting OTLP/HTTP spans with token counts to
either a local Jaeger instance or Harness Cloud & AI Cost Management
(CACM).

## Which setup this matches

Use this if your app already calls the Anthropic Python SDK directly
(`anthropic.Anthropic().messages.create(...)`) and you want cost and
token data in CACM without hand-rolling OpenTelemetry spans yourself. See
the Harness docs' Cloud & AI Cost Management → AI Traces → "Harness OTel
SDK" integration page for the underlying product concepts this demo
exercises.

If you don't call the Anthropic SDK directly (e.g. you go through
LiteLLM, or a different provider), see the other folders under
`1-harness-sdk/` once they land, or `3-manual-instrumentation/python/`
for a no-SDK approach.

## Prerequisites

- Python >= 3.10
- [`uv`](https://docs.astral.sh/uv/)
- **Local mode (default):** nothing else. Unlike `openai/`, there's no
  local-Ollama-style zero-cost provider path here — Anthropic has no
  OpenAI-API-compatible local runtime this demo can point at instead — so
  the shipped `.env.example` points at
  [`mock-providers/mock_anthropic_server.py`](../../mock-providers/README.md)
  instead: a stub that answers the Anthropic wire format with canned
  responses. No Anthropic account, no Harness account/token needed. To
  use the real Anthropic API instead (real model output, real token
  counts), get an API key and see "Setup" below.
- **Harness mode:** a Harness account ID and an ordinary personal/
  service-account token, sent natively as `x-harness-service-token` (see
  `docs/01-get-your-token.md`), in addition to a real Anthropic key (the
  mock only proves the plumbing works — see `mock-providers/README.md`).

## Setup

```bash
cp .env.example .env
```

Local mode works with the file as shipped against the mock server (start
it first — see "Run" below). To use the real Anthropic API instead, clear
`ANTHROPIC_BASE_URL` and put a real key in `ANTHROPIC_API_KEY`. To also
send traces to a real Harness account, edit two more lines:

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

In a separate terminal, leave this running (skip if using a real ANTHROPIC_API_KEY):

```bash
uv run ../../mock-providers/mock_anthropic_server.py
```

Then, in this terminal:

```bash
uv run main.py
```

Expected console output against the real Anthropic API (the severity label
is deterministic — a forced tool call at `temperature=0`; the summary and
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
`critical` (same forced tool call), but the summary and draft reply are
both the mock's fixed line, `This is a stubbed CI response for the demo
scenario.` — expected; it proves the trace pipeline works, not the model.

Local mode: open http://localhost:16686, find service `cacm-demo-anthropic`.
Harness mode: see `docs/02-verify-traces.md` for the Cost Explorer path.

## What to look for

**One trace, four spans.** Unlike naively calling `messages.create()`
three times with nothing wrapping them — which would produce three
unrelated root traces, since anthropic's auto-instrumentation opens and
closes each call's span entirely inside that single call, with nothing
left "current" afterward for the next call to attach to — `main.py` wraps
all three calls in one manually-created parent span,
`support_ticket_triage`. That's what makes this a real single-trace
waterfall instead of three disconnected traces:

| Span | Key attributes | Where it surfaces in Cost Explorer |
|---|---|---|
| `support_ticket_triage` (parent, hand-created) | `custom.ticket_severity` from STEP 5 — no `gen_ai.*` attributes; this span isn't a provider call | AI Traces → Service Traces drawer, the trace root |
| `chat <model>` (classify severity) | `gen_ai.provider.name=anthropic`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens` | first child span in the waterfall |
| `chat <model>` (summarize) | same attribute set; larger `input_tokens` than the first call (same ticket text, different system prompt) | second child span in the waterfall |
| `chat <model>` (draft reply) | same attribute set; largest `input_tokens` — this call carries calls 1+2's output as context | third child span in the waterfall; token growth here is what drives most of this trace's cost |

**`custom.ticket_severity` lives on the parent span, not on any `chat`
span.** `set_span_attribute` only affects whichever span OpenTelemetry
considers "current" at the moment it's called — and each `chat` span is
already closed by the time its own `messages.create()` call returns, so
nothing set after any of them would land there. Placing the enrichment
call inside the `support_ticket_triage` `with` block (still open across
all three calls) is what makes it actually take effect; see `main.py`'s
STEP 4/STEP 5 comments.

**`gen_ai.usage.input_tokens` here is cache-EXCLUSIVE.** The Anthropic
Python SDK's own `usage.input_tokens` field excludes cache reads and cache
writes — this app never sends cache-control breakpoints, so the
distinction doesn't fire on every call, but the attribute's *definition*
is still cache-exclusive, unlike some other providers' SDKs. (Running
against `mock-providers/`'s stub instead of a real key: every span reports
the same fixed `input_tokens: 42` / `output_tokens: 8` regardless of call
— the mock proves the attributes populate, it doesn't reproduce this
cache-token nuance. Use a real `ANTHROPIC_API_KEY` to see it.) This differs
from [`1-harness-sdk/litellm/`](../litellm/README.md): LiteLLM normalizes
usage to the OpenAI convention, where `prompt_tokens` *includes* cache
reads and writes. For requests that exercise Anthropic prompt caching,
`litellm/`'s reported input tokens will run higher than this app's for
logically the same request — don't sum `gen_ai.usage.input_tokens` across
the two apps' traces as if they measured the same thing. See
`litellm/README.md` "What to look for" for the full explanation.

## How it works

The instrumenting code is four lines, all in `main.py`:

```python
os.environ["HARNESS_ENABLE_AI_ANTHROPIC"] = "true"   # STEP 1 — opt in per provider
agent = Agent()                                        # STEP 2
agent.instrument()                                     # STEP 2 — before importing anthropic
import anthropic                                        # STEP 3 — only after instrument()
```

`Agent().instrument()` patches the `anthropic` client class so every
`create()` call gets wrapped in a span automatically — the app never sets
a `gen_ai.*` attribute by hand. The three `client.messages.create(...)`
calls and the printed output are ordinary application code beyond that.

One more piece of tracing-specific code, not part of the four lines
above: `main.py` opens its own span (`tracer.start_as_current_span(...)`)
around all three calls before making them. This isn't optional
boilerplate — without it, the three calls would land as three
disconnected root traces instead of one waterfall, since each
auto-created `chat` span's lifetime is scoped entirely to its own
`messages.create()` call (see "What to look for" above). It's also the
only reason STEP 5's `set_span_attribute` call has anywhere valid to
attach to.

## Adapt this to your app

**Change freely:**
- The scenario (`SUPPORT_TICKET`, the three calls, the tool schema) —
  replace with your own prompts and calls.
- `ANTHROPIC_MODEL` — point at any Anthropic model your account has
  access to.
- `HARNESS_SERVICE_NAME` — set to your actual service's name.
- The `custom.*` attribute name/value in STEP 5.

**Must not move:**
- The `agent.instrument()` call must stay before `import anthropic` (STEP
  2 → STEP 3 ordering). This is the one rule that silently breaks
  tracing with no error if violated.
- `opentelemetry-instrumentation-anthropic` and `opentelemetry-util-genai`
  must stay explicit dependencies in `pyproject.toml`, not left to
  `harness-sdk[anthropic]`'s transitive resolution — see the comments
  there for why.
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
