# Get your token

Every demo in this repo defaults to `TRACE_TARGET=local` and needs none of
this. Read this page only when you're ready to switch a demo to
`TRACE_TARGET=harness` and send traces to your real Harness account.

## What you need

Three values, all interpolated from **one** account ID — see "why one
account ID" below:

| Value | Where it comes from | Goes in `.env` as |
|---|---|---|
| Account ID | Your Harness account settings | `HARNESS_ACCOUNT_ID` |
| API token | A personal access token (PAT) or service account token (SAT), scoped to that account | `HARNESS_REPORTING_TOKEN` |
| Ingest base URL | The cluster your account lives on (table below) | `INGEST_BASE` |

Create the token from **Account Settings → My API Keys** (personal token)
or **Account Settings → Service Accounts** (service account token). Either
works — this repo's demos only need whatever privilege lets a token send
OTLP spans to the ingest endpoint. Don't create anything broader than
that "just in case."

## Cluster host reference

`INGEST_BASE` is a free-form base URL, not something a demo picks for
you — you supply the host matching where your account lives:

| Environment | Base URL |
|---|---|
| QA | `https://qa.harness.io/udp-ingest` |
| Prod0–4 | `https://prod{0..4}.harness.io/udp-ingest` |
| EU1 | `https://udp-eu1.harness.io/udp-ingest` |

If you don't know which cluster your account is on, ask whoever
provisioned it rather than guessing — sending to the wrong cluster fails
closed (auth error), it doesn't silently land somewhere else.

> The public CACM docs list cluster hosts as `app*.harness.io`. Those are
> stale for this purpose; use the hosts above.

## Why one account ID, not four

Every demo sends the account ID in four different places on the wire:

1. `x-tenant-id` header
2. `accountIdentifier` query param
3. `routingId` query param
4. `harness.account.id` resource attribute (in the OTLP payload itself,
   not a header)

Every app in this repo builds all four from your single
`HARNESS_ACCOUNT_ID` value, so there is exactly one place to get the
account ID wrong instead of four. If you ever see spans reaching the
gateway but never landing — or a hard `403 tenant mismatch` — that's this
value disagreeing with the token's own account. See
`04-troubleshooting.md`.

## What each demo actually sends

Given `HARNESS_ACCOUNT_ID` and `HARNESS_REPORTING_TOKEN`, every demo builds:

| Piece | Value | Required? |
|---|---|---|
| `x-harness-service-token` header | your token | Yes |
| `x-tenant-id` header | your account ID | No — safe to omit with `x-harness-service-token` present, sent for explicitness |
| `?accountIdentifier=…&routingId=…` | your account ID, twice | No — included for gateway routing |
| `harness.account.id` resource attribute | your account ID | No — the gateway derives the account from the token if this is absent. **If present, it must match the token's account or ingestion hard-fails with `403 tenant mismatch`.** |

Every demo in this repo sends `x-harness-service-token` — the same header
the Harness SDK's `HARNESS_REPORTING_TOKEN` env var sends natively. The
platform/UDP team confirmed (2026-09-21) that unless a token is
explicitly minted by the platform team as an admin-token, this header's
tenant check is enforced exactly like any other credential's — it is not
a bypass. An earlier version of this page called it an admin/
cross-account credential and told readers to avoid it; that was wrong and
has been corrected.

## Once you have all three values

Edit two lines in the demo's `.env` (the third, `INGEST_BASE`, already
ships with a sensible default — change it only if your account isn't on
that cluster):

```bash
TRACE_TARGET=harness
HARNESS_ACCOUNT_ID=<your account id>
HARNESS_REPORTING_TOKEN=<your token>
```

Then run the demo as its own `README.md` describes, and see
`02-verify-traces.md` for where the resulting trace shows up in CACM.
