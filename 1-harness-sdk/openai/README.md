# `1-harness-sdk/openai/`

## What this shows

The Harness OTel SDK's OpenAI GenAI instrumentation, end to end: a
three-call support-ticket triage script built on `harness-sdk[openai]` +
`openai>=2.x`, exporting OTLP/HTTP spans with token counts to either a
local Jaeger instance or Harness Cloud & AI Cost Management (CACM).

## Which setup this matches

Use this if your app already calls the OpenAI Python SDK directly
(`openai.OpenAI(...).chat.completions.create(...)`) and you want cost and
token data in CACM without hand-rolling OpenTelemetry spans yourself. See
the Harness docs' Cloud & AI Cost Management → AI Traces → "Harness OTel
SDK" integration page for the underlying product concepts this demo
exercises.

If you don't call the OpenAI SDK directly (e.g. you go through LiteLLM, or
a different provider), see the other folders under `1-harness-sdk/` once
they land, or `3-manual-instrumentation/python/` for a no-SDK approach.

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
  service-account token, sent natively as `x-harness-service-token` (see
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

Local mode: open http://localhost:16686, find service `cacm-demo-openai`.
Harness mode: see `docs/02-verify-traces.md` for the Cost Explorer path.

## What to look for

**One trace, four spans.** Unlike naively calling `chat.completions.create()`
three times with nothing wrapping them — which would produce three
unrelated root traces, since openai's auto-instrumentation opens and
closes each call's span entirely inside that single call, with nothing
left "current" afterward for the next call to attach to — `main.py` wraps
all three calls in one manually-created parent span,
`support_ticket_triage`. That's what makes this a real single-trace
waterfall instead of three disconnected traces:

| Span | Key attributes | Where it surfaces in Cost Explorer |
|---|---|---|
| `support_ticket_triage` (parent, hand-created) | `custom.ticket_severity` from STEP 5 — no `gen_ai.*` attributes; this span isn't a provider call | AI Traces → Service Traces drawer, the trace root |
| `chat <model>` (classify severity) | `gen_ai.provider.name=openai`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens` | first child span in the waterfall |
| `chat <model>` (summarize) | same attribute set; larger `input_tokens` than the first call (same ticket text, different system prompt) | second child span in the waterfall |
| `chat <model>` (draft reply) | same attribute set; largest `input_tokens` — this call carries calls 1+2's output as context | third child span in the waterfall; token growth here is what drives most of this trace's cost |

`gen_ai.usage.input_tokens` here is a straight passthrough of the OpenAI
API's own `prompt_tokens` — nothing about this app's usage inflates or
excludes cache tokens the way some other providers' SDKs do.

**`custom.ticket_severity` lives on the parent span, not on any `chat`
span.** `set_span_attribute` only affects whichever span OpenTelemetry
considers "current" at the moment it's called — and each `chat` span is
already closed by the time its own `chat.completions.create()` call
returns, so nothing set after any of them would land there. Placing the
enrichment call inside the `support_ticket_triage` `with` block (still
open across all three calls) is what makes it actually take effect; see
`main.py`'s STEP 4/STEP 5 comments.

## How it works

The instrumenting code is four lines, all in `main.py`:

```python
os.environ["HARNESS_ENABLE_AI_OPENAI"] = "true"   # STEP 1 — opt in per provider
agent = Agent()                                    # STEP 2
agent.instrument()                                 # STEP 2 — before importing openai
import openai                                       # STEP 3 — only after instrument()
```

`Agent().instrument()` patches the `openai` client class so every
`create()` call gets wrapped in a span automatically — the app never sets
a `gen_ai.*` attribute by hand. The three `client.chat.completions.create(...)`
calls and the printed output are ordinary application code beyond that.

One more piece of tracing-specific code, not part of the four lines
above: `main.py` opens its own span (`tracer.start_as_current_span(...)`)
around all three calls before making them. This isn't optional
boilerplate — without it, the three calls would land as three
disconnected root traces instead of one waterfall, since each
auto-created `chat` span's lifetime is scoped entirely to its own
`chat.completions.create()` call (see "What to look for" above). It's
also the only reason STEP 5's `set_span_attribute` call has anywhere
valid to attach to.

## Adapt this to your app

**Change freely:**
- The scenario (`SUPPORT_TICKET`, the three calls, the tool schema) —
  replace with your own prompts and calls.
- `OPENAI_MODEL` / `OPENAI_BASE_URL` — point at any OpenAI-API-compatible
  endpoint.
- `HARNESS_SERVICE_NAME` — set to your actual service's name.
- The `custom.*` attribute name/value in STEP 5.

**Must not move:**
- The `agent.instrument()` call must stay before `import openai` (STEP
  2 → STEP 3 ordering). This is the one rule that silently breaks
  tracing with no error if violated.
- `httpx` must stay an explicit dependency in `pyproject.toml` as long as
  you depend on `openai>=2.x`.
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
