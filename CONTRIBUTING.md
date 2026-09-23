# Contributing

All contributions require a signed Contributor License Agreement — see
[`CLA.md`](CLA.md).

This repo is a flat collection of independent, copy-paste demo apps. There
is no shared abstraction layer across apps — duplication between folders is
intentional, not a cleanup opportunity. Each app must stand on its own if
someone copies just that one folder out of the repo.

## Adding a new app

1. Pick the target from the matrix in the root `README.md`.
2. Copy the nearest existing app in the same family as a starting point
   rather than writing one from scratch — new apps are diffs against an
   existing template, not novel designs.
3. Follow the file contract and README spec below exactly.
4. Make sure it runs end-to-end in local mode (against `local-collector/`)
   before opening a PR. Harness-mode (real CACM ingestion) is verified
   manually — see `docs/03-run-locally-first.md` — not part of CI.

## Per-app file contract

Every leaf app folder contains exactly these files:

| File | Rule |
|---|---|
| `README.md` | The 8 fixed sections below, same headings, same order, in every app |
| `pyproject.toml` | `requires-python = ">=3.10"`; dependencies pinned with lower bounds; a comment on every non-obvious dependency explaining why it's there |
| `uv.lock` | Committed. A broken upstream release must not break the demo |
| `.env.example` | Every variable the app reads, grouped Harness / provider / local; `TRACE_TARGET=local` by default |
| `main.py` | Single file. Numbered `STEP n —` block comments |

No extra files, no missing ones — except the documented exceptions below.

### Exceptions

| Folder | Deviation |
|---|---|
| `2-open-source-sdks/litellm-proxy/` | `main.py` replaced by `config.yaml` + `docker-compose.yaml` |
| `2-open-source-sdks/claude-code/` | Only `README.md` + a `settings.json` snippet; no `pyproject.toml`/`uv.lock`/`main.py` |
| `3-manual-instrumentation/go/` | `go.mod` + `main.go` instead of the Python file set |

## README spec

Every app's `README.md` has these 8 sections, identical headings, identical order:

1. **What this shows** — one sentence, plus the exact stack combination.
2. **Which setup this matches** — "use this if your app does X"; links to the canonical Harness doc page.
3. **Prerequisites** — Python version, `uv`, which provider key, whether a Harness token is needed (not needed in local mode).
4. **Setup** — `cp .env.example .env`, edit two lines, `uv sync`.
5. **Run** — the run command, plus verbatim expected console output.
6. **What to look for** — table of exact span name + `gen_ai.*` attributes this app produces, and where they surface in Cost Explorer.
7. **How it works** — only the 3–5 lines that do the instrumenting. Nothing about the demo's business logic.
8. **Adapt this to your app** — what to change, what must not move.

## `main.py` structure

Applies to every script-style app (i.e. all apps except the exceptions above):

```
STEP 1 — Configure via environment (before any other import)
STEP 2 — Instrument
STEP 3 — Import the provider client / build the app   (order matters — see below)
STEP 4 — Run the scenario
STEP 5 — Enrich spans with custom business attributes
STEP 6 — Flush before exit
```

## Constraints every app must encode (in comments, not just behavior)

1. **Instrument before import.** The instrumentation call must execute
   before importing the provider SDK (`openai`, `anthropic`,
   `google.genai`, …). Patching happens at import time — the wrong order
   silently drops every span, with no error or warning.
2. **`openai>=2.x` needs an explicit `httpx` dependency.** `openai>=2.x`
   vendors a renamed `httpx` and no longer depends on plain `httpx`, but the
   OpenAI OTel instrumentor imports `httpx` directly. Without it as an
   explicit dependency, the instrumentor silently no-ops.
3. **Console span exporters are typically exclusive, not additive** in
   these SDKs — enabling one usually replaces OTLP export rather than
   supplementing it. Every demo ships it off, with a comment explaining why.
4. **No implicit flush on exit.** A batch span processor's default flush
   delay outlives a short script. Every script-style app ends with an
   explicit flush call (`main.py` STEP 6). The long-lived service app uses
   graceful shutdown handling instead.

## Before opening a PR

- [ ] File set matches the contract above exactly (exceptions table respected)
- [ ] `README.md` has all 8 sections, in order
- [ ] `uv sync --locked` succeeds and the app runs against a local Jaeger
- [ ] No secrets, tokens, or internal references committed
- [ ] No sample code sends any credential other than `x-harness-service-token` /
      `x-tenant-id` — no admin or cross-account header of any kind
