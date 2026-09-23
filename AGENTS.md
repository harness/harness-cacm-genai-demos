# AGENTS.md

Agent-facing mirror of `CONTRIBUTING.md`. Read that file for the full file
contract, README spec, and per-app constraints — this file only adds notes
specific to working here as a coding agent. If this file and
`CONTRIBUTING.md` ever disagree, `CONTRIBUTING.md` wins.

## What this repo is

A flat set of independent, copy-paste demo apps, one per supported way of
sending GenAI traces into Harness CACM. There is no shared code between
app folders — do not introduce a shared library, base class, or common
`utils.py` across apps, even if you notice duplication. The duplication is
intentional: each folder must work if a user copies only that one folder
out of the repo.

## Before creating or editing an app folder

- Copy the nearest existing app in the same family as your starting point.
  Do not design a new app from scratch — every app is a deliberate diff
  against an existing one.
- Match the file contract in `CONTRIBUTING.md` exactly: don't add files
  beyond the contract (no `utils.py`, no `constants.py`, no test folder)
  and don't omit any of the required ones, except for the three documented
  exceptions (`litellm-proxy/`, `claude-code/`, `go/`).
- Keep `main.py` a single file with the numbered `STEP n —` comments. Don't
  split it into modules even if it feels long.

## Constraints you must not silently drop

These four runtime behaviors are easy to regress because none of them
raise an error or warning when violated — they just silently produce no
spans, or spans that go nowhere:

1. **Instrument before import** — the instrumentation call must run before
   the provider SDK is imported. Keep the provider import inside the
   function body, after instrumentation, with a comment explaining why.
2. **`openai>=2.x` needs an explicit `httpx` dependency** in `pyproject.toml`
   even though nothing in the app code imports `httpx` directly.
3. **Console exporters replace OTLP export, they don't add to it** — any
   demo enabling one must ship it `false`/off by default, with a comment.
4. **Every script-style app must end with an explicit flush call.** Don't
   assume the batch span processor flushes on exit — it doesn't within a
   short script's lifetime.

If you touch an existing app's `main.py`, verify all four are still true
and still commented, not just still working by accident.

## Things that must never appear in this repo

- Any provider API key, Harness API token, or account ID — not even as a
  "just for local testing" placeholder value beyond what's already in
  `.env.example` (which ships only variable names, no values).
- Any credential/header other than `x-harness-service-token` and
  `x-tenant-id` for reaching the Harness ingest endpoint. An ordinary
  personal/service-account token sent as `x-harness-service-token` is
  fine — that's exactly what every app in this repo sends, and it gets
  normal tenant-check enforcement, not a bypass. The rule is specifically:
  never introduce a platform-team-minted admin or cross-account
  credential of any kind into sample code.
- Internal tooling names, ticket prefixes, internal hostnames, or Slack
  channel references. This is a public repo; keep it generic.

## Before finishing a PR-sized change

Run through the checklist at the bottom of `CONTRIBUTING.md`. Don't mark a
new app "done" without actually running it against `local-collector/` and
confirming spans show up at `http://localhost:16686`.
