# Verify your traces in CACM

This page walks through where a demo's spans surface once you've switched
it to `TRACE_TARGET=harness` (see `01-get-your-token.md`) and run it. If
you're still in local mode, you want `03-run-locally-first.md` instead —
this page is CACM-specific.

## Where to look

1. Open **Cost Explorer** in your Harness account.
2. Go to **AI Traces**.
3. Find the service by the name the demo sent — every demo sets a
   distinct `service.name` (e.g. `cacm-demo-openai`,
   `cacm-demo-anthropic`, `cacm-demo-manual-python`; each app's own
   `README.md` "Run" section states its exact value).
4. Open that service's **Service Traces** drawer.

What you see depends on the app: every `1-harness-sdk/*` app sends **one
trace** with a parent span plus one child span per provider call (see the
note below); `3-manual-instrumentation/python/` sends **three separate
traces**, each with one span, since nothing there propagates a shared
trace context across its three hand-rolled spans.

## What you should see per span

Every app's own `README.md` has a "What to look for" section with the
exact attribute set that app puts on its spans. In general, expect:

- `gen_ai.provider.name` — which pricing table Cost Explorer uses.
- `gen_ai.request.model` — which rate *within* that provider.
- `gen_ai.usage.input_tokens` / `gen_ai.usage.output_tokens` — what the
  dollar cost is computed from.
- `gen_ai.agent.name` (Family 3 apps) — needed for the span's cost to
  roll up under an agent in the per-agent breakdown, rather than only the
  raw per-service total.

If a dollar cost is showing next to each span, ingestion and cost
attribution both worked end to end. If spans appear but show token counts
with **no** dollar figure, see `04-troubleshooting.md` — that's almost
always a missing `gen_ai.provider.name` or `gen_ai.request.model`, not a
transport problem.

## One trace, one parent span, three children — except `3-manual-instrumentation/python/`

Every `1-harness-sdk/*` app's `main.py` wraps its three demo calls
(classify/summarize/draft) in one manually-created parent span
(`support_ticket_triage`) before making them, specifically so the three
calls land as one connected trace instead of three disconnected ones —
each of those instrumentors opens and closes its own provider-call span
entirely inside a single call, so without an explicit parent span held
open across all three, nothing would be "current" for the second and
third calls to attach to, and they'd land as unrelated root traces. The
parent span itself carries no `gen_ai.*` attributes — it isn't a provider
call — but does carry the `custom.*` business attribute each app's STEP 5
sets (see that app's own "What to look for").

`3-manual-instrumentation/python/` is the one exception: it doesn't
establish a shared parent span, so its three calls really do land as
three separate single-span traces under the same service — that's the
correct, expected shape for that app specifically, not a bug.

[`2-open-source-sdks/litellm-proxy/`](../2-open-source-sdks/litellm-proxy/README.md)
is a third, differently-shaped case — not really an exception to the rule
above so much as outside it: there's no Python process and no
manually-created parent span at all, yet its three requests still land as
one trace, because `request.sh` sends the same W3C `traceparent` header on
all three `curl` calls. The proxy's own `otel` callback then attaches a
7-span internal call tree to each request, for 21 spans total rather than
the `1-harness-sdk/*` apps' 4 — see that app's own "What to look for" for
the full shape and which 2 of those 21 spans actually carry `gen_ai.*`
data.

## If nothing shows up at all

Don't debug blind — go straight to `04-troubleshooting.md`, which is
organized by exactly this kind of symptom ("no spans at all" vs. "spans
with no cost" vs. "`403 tenant mismatch`") rather than by cause.
