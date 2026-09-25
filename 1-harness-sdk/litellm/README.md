# `1-harness-sdk/litellm/`

## What this shows

The Harness OTel SDK's LiteLLM GenAI instrumentation, end to end: the same
three-call support-ticket triage script as `1-harness-sdk/anthropic/`, but
calling `litellm.completion()` instead of the Anthropic Python SDK
directly, built on `harness-sdk[litellm]` + `litellm`, exporting OTLP/HTTP
spans with token counts to either a local Jaeger instance or Harness Cloud
& AI Cost Management (CACM).

## Which setup this matches

Use this if your app calls providers through LiteLLM's `litellm.completion()`
/ `litellm.acompletion()` (direct import, not the LiteLLM proxy) and you
want cost and token data in CACM without hand-rolling OpenTelemetry spans
yourself. See the Harness docs' Cloud & AI Cost Management → AI Traces →
"Harness OTel SDK" integration page for the underlying product concepts
this demo exercises.

If you run the **LiteLLM proxy** instead of importing `litellm` directly,
see [`2-open-source-sdks/litellm-proxy/`](../../2-open-source-sdks/litellm-proxy/README.md)
instead — that's a separate integration path with its own OTel callback,
not this app. If you call a provider SDK directly with no LiteLLM in
between, see `1-harness-sdk/openai/` or `1-harness-sdk/anthropic/`
instead.

## Prerequisites

- Python >= 3.10
- [`uv`](https://docs.astral.sh/uv/)
- **Local mode (default):** nothing else. This demo's `LITELLM_MODEL`
  default (`anthropic/claude-haiku-4-5`) routes to the Anthropic API
  through LiteLLM, and — like `anthropic/`, and unlike `openai/` — there's
  no local-Ollama-style zero-cost path for it, so the shipped
  `.env.example` points `LITELLM_API_BASE` at
  [`mock-providers/mock_anthropic_server.py`](../../mock-providers/README.md)
  instead: a stub that answers the Anthropic wire format with canned
  responses. No Anthropic account, no Harness account/token needed. To use
  the real Anthropic API instead (real model output, real token counts),
  get an API key and see "Setup" below.
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
`LITELLM_API_BASE` and put a real key in `ANTHROPIC_API_KEY`. To also send
traces to a real Harness account, edit two more lines:

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

Local mode: open http://localhost:16686, find service `cacm-demo-litellm`.
Harness mode: see `docs/02-verify-traces.md` for the Cost Explorer path.

## What to look for

**One trace, four spans.** Unlike naively calling `litellm.completion()`
three times with nothing wrapping them — which would produce three
unrelated root traces, since litellm's auto-instrumentation opens and
closes each call's `litellm_request` span entirely inside that single
call, with nothing left "current" afterward for the next call to attach
to — `main.py` wraps all three calls in one manually-created parent span,
`support_ticket_triage`. That's what makes this a real single-trace
waterfall instead of three disconnected traces. Unlike `openai/` and
`anthropic/`, the three child spans here all share the same name —
`litellm_request` — regardless of the underlying model or provider;
LiteLLM's instrumentor names the span after itself, not after the routed
model.

| Span | Key attributes | Where it surfaces in Cost Explorer |
|---|---|---|
| `support_ticket_triage` (parent, hand-created) | `custom.ticket_severity` from STEP 5 — no `gen_ai.*` attributes; this span isn't a provider call | AI Traces → Service Traces drawer, the trace root |
| `litellm_request` (classify severity) | `gen_ai.provider.name=anthropic`, `gen_ai.request.model`, `gen_ai.framework=litellm`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.usage.total_tokens` | first child span in the waterfall |
| `litellm_request` (summarize) | same attribute set; larger `input_tokens` than the first call (same ticket text, different system prompt) | second child span in the waterfall |
| `litellm_request` (draft reply) | same attribute set; largest `input_tokens` — this call carries calls 1+2's output as context | third child span in the waterfall; token growth here is what drives most of this trace's cost |

**`custom.ticket_severity` lives on the parent span, not on any
`litellm_request` span.** `set_span_attribute` only affects whichever
span OpenTelemetry considers "current" at the moment it's called — and
each `litellm_request` span is already closed by the time its own
`completion()` call returns, so nothing set after any of them would land
there. Placing the enrichment call inside the `support_ticket_triage`
`with` block (still open across all three calls) is what makes it
actually take effect; see `main.py`'s STEP 4/STEP 5 comments.

Two attributes appear here that `anthropic/`'s spans don't carry:
`gen_ai.framework=litellm` (set on every span this instrumentor produces,
naming the framework doing the routing) and `gen_ai.usage.total_tokens`
(set unconditionally from LiteLLM's own usage payload — most instrumentors
in this repo leave it unset).

**`gen_ai.usage.input_tokens` here follows the OpenAI convention, which is
cache-INCLUSIVE — this differs from `1-harness-sdk/anthropic/`'s
cache-EXCLUSIVE definition of the same attribute, for the same underlying
Anthropic model.** The Anthropic Python SDK's own `usage.input_tokens`
excludes cache reads and cache writes (see `anthropic/README.md` "What to
look for"). LiteLLM normalizes every provider's usage to the OpenAI
convention before handing it to the instrumentor, and the OpenAI
convention folds cache reads *and* cache writes into `prompt_tokens`. This
app and `anthropic/` both call the same model with no cache-control
breakpoints set, so in a single side-by-side run of the two apps the raw
numbers will typically match — the divergence isn't visible until either
app's traffic actually exercises Anthropic prompt caching (repeated calls
that reuse a cached prefix). At that point this app's `input_tokens` runs
**higher** than `anthropic/`'s for logically the same request, because it
now includes tokens `anthropic/`'s definition excludes. **Don't sum
`gen_ai.usage.input_tokens` across this app's traces and `anthropic/`'s as
if they measured the same thing** — the attribute name is identical, the
definition is not.

(Running against `mock-providers/`'s stub instead of a real key: every
span reports the same fixed `input_tokens: 42` / `output_tokens: 8`
regardless of call or app, so this cache-inclusive-vs-exclusive divergence
isn't visible at all in mock mode — it only shows up against the real
Anthropic API. The mock proves the attributes populate, not this specific
behavior.)

## How it works

The instrumenting code is four lines, all in `main.py`:

```python
os.environ["HARNESS_ENABLE_AI_LITELLM"] = "true"   # STEP 1 — opt in
agent = Agent()                                      # STEP 2
agent.instrument()                                   # STEP 2 — before importing litellm
import litellm                                        # STEP 3 — only after instrument()
```

`Agent().instrument()` wraps LiteLLM's `completion`/`acompletion` (and
related) functions so every call gets wrapped in a span automatically —
the app never sets a `gen_ai.*` attribute by hand. The three
`litellm.completion(...)` calls and the printed output are ordinary
application code beyond that.

One more piece of tracing-specific code, not part of the four lines
above: `main.py` opens its own span (`tracer.start_as_current_span(...)`)
around all three calls before making them. This isn't optional
boilerplate — without it, the three calls would land as three
disconnected root traces instead of one waterfall, since each
auto-created `litellm_request` span's lifetime is scoped entirely to its
own `completion()` call (see "What to look for" above). It's also the
only reason STEP 5's `set_span_attribute` call has anywhere valid to
attach to.

## Adapt this to your app

**Change freely:**
- The scenario (`SUPPORT_TICKET`, the three calls, the tool schema) —
  replace with your own prompts and calls.
- `LITELLM_MODEL` — point at any LiteLLM-supported model string
  (`bedrock/...`, `openai/...`, `vertex_ai/...`, ...). Changing the
  provider prefix likely means changing which credential env var this app
  needs — this demo only wires up `ANTHROPIC_API_KEY` for the default
  `anthropic/...` routing.
- `HARNESS_SERVICE_NAME` — set to your actual service's name.
- The `custom.*` attribute name/value in STEP 5.

**Must not move:**
- The `agent.instrument()` call must stay before `import litellm` (STEP
  2 → STEP 3 ordering) — see the comment in `main.py` STEP 2 for how this
  instrumentor's mechanism differs slightly from `openai/`/`anthropic/`'s,
  and why the ordering convention is still followed regardless.
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
