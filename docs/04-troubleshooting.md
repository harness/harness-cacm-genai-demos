# Troubleshooting: "no spans appeared"

Keyed by symptom, not by cause — find what you're actually seeing (or not
seeing) below. Every symptom here is a case where a demo runs to
completion, prints its normal output, and exits `0` — none of these are
crashes, which is exactly what makes them easy to miss.

## Symptom: I see no spans at all — not in Jaeger, not in CACM

Work through these in order:

1. **Is `local-collector/` actually running (local mode)?**
   `docker-compose up -d` inside `local-collector/`, then check
   `http://localhost:16686` loads before blaming the demo.
   [`2-open-source-sdks/litellm-proxy/`](../2-open-source-sdks/litellm-proxy/README.md)
   is the one app this doesn't apply to — its own `docker-compose.yaml`
   bundles a separate Jaeger instead of using `local-collector/`'s; run
   `docker-compose up -d` inside that app's own folder, not the repo
   root's.

2. **Is something else already bound to `127.0.0.1:4318`?**
   Every demo's `.env.example` points `LOCAL_OTLP_ENDPOINT` at `4418`, not
   the OTel default `4318`, specifically because it's common for another
   local agent to already own `4318`, answer `HTTP 200`, and silently
   discard the payload — no error anywhere. If you changed
   `LOCAL_OTLP_ENDPOINT` back to `4318` (or a custom app config did), put
   it back to `4418` and re-run.

3. **(Family 1 apps only) Is `agent.instrument()` really running before
   `import openai` / `import anthropic` / `import litellm` / `from google
   import genai`?** Instrumentation patches the provider client at
   *import* time. If the provider module is imported anywhere —
   including transitively, by another import above it — before
   `Agent().instrument()` runs, every call from that client is silently
   unpatched and produces zero spans, with no exception and no log line.
   Check `main.py`'s STEP 2 → STEP 3 ordering — see
   [`1-harness-sdk/litellm/`](../1-harness-sdk/litellm/README.md) and
   [`1-harness-sdk/google-genai-vertex/`](../1-harness-sdk/google-genai-vertex/README.md)'s
   own "How it works" sections if either instrumentor's ordering looks
   different from `openai/`'s or `anthropic/`'s.

4. **(`1-harness-sdk/openai/` specifically) Is `httpx` an explicit
   dependency?** `openai>=2.x` vendors its own renamed `httpx` internally
   and no longer pulls in plain `httpx` as a dependency — but
   `opentelemetry-instrumentation-openai_v2` imports `httpx` directly to
   do its patching. If `httpx` isn't pinned in `pyproject.toml`, the
   instrumentor silently no-ops instead of failing to install. This is
   fixed permanently in this repo's own `uv.lock`, but matters if you
   stripped `httpx` while adapting the demo.

5. **Did the script exit before the batch span processor flushed?** A
   `BatchSpanProcessor` batches on a delay that outlives a short script's
   process lifetime by default. Every app in this repo ends with an
   explicit flush call (STEP 6) for exactly this reason — if you removed
   or commented it out while adapting a demo, put it back.

## Symptom: spans show up on stdout, but nothing reaches Jaeger or CACM

`HARNESS_ENABLE_CONSOLE_SPAN_EXPORTER=true` **replaces** OTLP export, it
doesn't add a second exporter alongside it. Every demo in this repo ships
it `false` for exactly this reason. If you flipped it to `true` to eyeball
span JSON, flip it back — you can't have both at once.

## Symptom: `403 tenant mismatch` (harness mode only)

Full error text: `tenant mismatch: token account does not match payload
account`. This means `HARNESS_ACCOUNT_ID` in your `.env` doesn't match the
account your `HARNESS_REPORTING_TOKEN` token actually belongs to — most
often because the token was rotated/replaced but the account ID wasn't
updated to match (or vice versa: an account ID left over from a different
account's `.env`). Every demo interpolates the same `HARNESS_ACCOUNT_ID`
into four different places on the wire, so there's exactly one value to
fix here, not four. See `01-get-your-token.md` for what those four places
are.

## Symptom: spans appear (in Jaeger or CACM), but with no dollar cost

The span reached ingestion fine — this is a missing-attribute problem,
not a transport problem. Cost Explorer needs, at minimum,
`gen_ai.provider.name` and `gen_ai.request.model` to price a span at all;
without token counts (`gen_ai.usage.input_tokens` /
`gen_ai.usage.output_tokens`) a span prices at exactly zero rather than
failing. `3-manual-instrumentation/python/README.md`'s "What to look for"
table has the full breakdown of which attribute's absence causes which
specific failure mode, since that's the app where you're setting these by
hand and most likely to drop one.

## Symptom: dollar cost looks right per-span, but doesn't roll up under an agent

Missing `gen_ai.agent.name` (Family 3 apps; Family 1/2 provider
instrumentors don't currently set this, either). The span still prices
correctly — it just shows up only in the raw per-service total in Cost
Explorer, not attributable to a specific agent in the per-agent
breakdown.

## Symptom: token counts look different for the "same" model between two demos

This is very likely not a bug — see `05-what-drives-cost.md`'s note on
cache-inclusive vs. cache-exclusive token counting before assuming
anything is broken. Different SDK paths to the same underlying model can
legitimately report different `gen_ai.usage.input_tokens` values for
identical input.
