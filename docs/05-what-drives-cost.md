# What drives cost

Cost Explorer computes a span's dollar cost from a small set of
`gen_ai.*` attributes. This page is the reference for exactly which ones,
and the sharp edges around token counting that make the same underlying
model call look like it costs different amounts depending on which demo
in this repo produced it.

## The attributes cost is computed from

| Attribute | What it determines | If missing |
|---|---|---|
| `gen_ai.provider.name` (or the older, deprecated `gen_ai.system` — both are accepted) | Which provider's rate table applies (OpenAI vs. Anthropic vs. …) | Span shows token counts with **no** dollar cost — there's no rate table to price against at all. |
| `gen_ai.request.model` | Which rate *within* that provider's table (e.g. `gpt-4o-mini` vs. `gpt-4o` — pricing can differ by ~20x for the same provider) | Same failure as above, one level more specific: provider known, exact rate unknown. |
| `gen_ai.usage.input_tokens` | The prompt-side half of the cost calculation | Cost computes as exactly zero for this span — no count to multiply a rate by. |
| `gen_ai.usage.output_tokens` | The completion-side half (usually the pricier side per token) | Span under-costs rather than zero-costs — input-token cost alone still applies. |
| `gen_ai.agent.name` | Whether this span's cost rolls up under an agent in the per-agent breakdown | Cost still computes correctly; it just only appears in the raw per-service total, not attributed to any agent. |

None of the apps in this repo currently set `gen_ai.usage.total_tokens` —
Cost Explorer derives total cost from the input/output split above, it
doesn't need a separate total.

[`2-open-source-sdks/litellm-proxy/`](../2-open-source-sdks/litellm-proxy/README.md)
is the one app in this repo that emits the older `gen_ai.system` key
instead of `gen_ai.provider.name` for that first row — see its own
README's "What to look for" for why.

## The sharp edge: cache-inclusive vs. cache-exclusive input tokens

**The same underlying model, called through a different SDK path, can
report a different `gen_ai.usage.input_tokens` value for identical
input** — because "prompt tokens" isn't defined the same way by every
provider SDK:

- **`1-harness-sdk/anthropic/`** reads `usage.input_tokens` straight off
  the Anthropic Python SDK's own response object. Anthropic's SDK
  **excludes** cache reads and cache writes from this field.
- **A LiteLLM-fronted path** — [`1-harness-sdk/litellm/`](../1-harness-sdk/litellm/README.md)
  normalizes usage to the OpenAI convention, where `prompt_tokens`
  **includes** cache reads and writes. For the same Anthropic model
  called both ways, the LiteLLM path's reported input tokens will run
  higher — not because more actually happened, but because the two SDKs
  define "prompt tokens" differently.
- **`1-harness-sdk/openai/`** and **`3-manual-instrumentation/python/`**
  both read `usage.prompt_tokens` straight off the OpenAI API's own
  response object (the same field, read two different ways — one by an
  instrumentor, one by hand). Their token counts agree with each other
  for the same input; that's a same-SDK comparison, not a same-model
  comparison across SDKs.

**Don't sum `gen_ai.usage.input_tokens` across spans produced by
different SDK paths as if they measured the same thing.** Comparing two
spans from the *same* app/SDK path is safe; comparing across apps in this
repo (or across your own app's providers, if you mix SDKs) is not, unless
you've confirmed both paths define the field the same way.

## Why manual instrumentation has a required-attribute table and the others don't

`1-harness-sdk/openai/`, `1-harness-sdk/anthropic/`,
[`1-harness-sdk/litellm/`](../1-harness-sdk/litellm/README.md), and
[`1-harness-sdk/google-genai-vertex/`](../1-harness-sdk/google-genai-vertex/README.md)
all get every attribute in the table above for free from a patched
client — there's nothing to drop by accident. `3-manual-instrumentation/python/` sets every one of
them by hand, on every span, so its own `README.md` "What to look for"
section spells out exactly what breaks in Cost Explorer if you drop any
one of them while adapting that demo to your own code. If you're building
your own manual instrumentation (no SDK, no auto-instrumentor), that
table is the one to work from.
