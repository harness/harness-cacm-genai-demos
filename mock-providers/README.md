# `mock-providers/`

Stdlib-only stub servers that answer a real provider's wire format closely
enough for that provider's OTel instrumentor to populate `gen_ai.*`
attributes from the response — so you can see a working trace before you
have (or want to spend) a real provider API key or Google Cloud ADC setup.

This is the exact same code `.github/workflows/ci.yml` runs — not a
separate CI-only fixture kept in sync by hand. If it works here, it works
in CI, and vice versa.

**Responses are canned, not real model output.** Every call gets a fixed
severity (`critical`), a fixed one-line summary/reply, and fixed token
counts (`input_tokens: 42`, `output_tokens: 8`). This proves the
instrumentation plumbing works — spans appear, `gen_ai.*` attributes are
populated — it does not demonstrate real model behavior or realistic cost
numbers. Once you've confirmed spans show up in Jaeger, switch to a real
provider key (real ADC credentials, for `google-genai-vertex/`; a local
Ollama instance is also an option for `1-harness-sdk/openai/` and
`3-manual-instrumentation/python/`, still with no provider account) to see
actual output.

## Which app uses which script

| Script | Answers | Used by |
|---|---|---|
| `mock_openai_server.py` | OpenAI `/v1/chat/completions` | `1-harness-sdk/openai/`, `3-manual-instrumentation/python/`, `2-open-source-sdks/litellm-proxy/` |
| `mock_anthropic_server.py` | Anthropic `/v1/messages` | `1-harness-sdk/anthropic/`, `1-harness-sdk/litellm/` (LiteLLM's `anthropic/...` routing hits the same wire shape) |
| `mock_google_genai_server.py` | Vertex AI `generateContent` | `1-harness-sdk/google-genai-vertex/` |

## Running one

Run one with `uv`, in its own terminal window, left running there while
you work in a second terminal for the app itself — backgrounding it with
`&` instead is easy to forget about and leave orphaned after you're done.
No `python3` install, no dependency install, nothing beyond `uv` itself:
each script carries a PEP 723 inline metadata block (`# /// script ...
///`) declaring no third-party dependencies, so `uv run` executes it in
its own throwaway environment, independent of any app's
`pyproject.toml`/`uv.lock`:

```bash
uv run mock-providers/mock_anthropic_server.py
```

Each script binds port `8080`. `mock_openai_server.py` binds `0.0.0.0` (so
`litellm-proxy`'s container can reach it via `host.docker.internal`); the
other two bind `127.0.0.1`.

Then, in your second terminal, follow the app's own README.md "Setup"/
"Run" section — its `.env.example` already ships pointed at this server by
default (`2-open-source-sdks/litellm-proxy/`'s `docker-compose.yaml` reads
the same default from its own `.env.example` rather than a `main.py`).
`1-harness-sdk/openai/` and `3-manual-instrumentation/python/` also
support pointing at a local Ollama instance instead, as a
real-model-output alternative — see those two apps' `.env.example` for the
commented-out block. Stop the server with Ctrl-C in its terminal once
you're done.

## Why this lives outside any single app folder

Every app folder is meant to be copyable out of this repo in isolation
(see root `AGENTS.md`) — same reason `local-collector/`'s Jaeger lives at
the repo root rather than being duplicated into every app. If you copy
just one app folder out, you lose this fast path the same way you'd lose
`local-collector/`'s Jaeger: bring your own stub, real key, or OTel
collector instead.
