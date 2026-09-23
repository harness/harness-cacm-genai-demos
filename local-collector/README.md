# local-collector

A single-container Jaeger instance for running any demo in this repo
without a Harness account, a provider API key (if you point the demo at a
local model), or any live spend.

## Start it

```bash
docker-compose up -d
```

This starts Jaeger with:

| Purpose | URL / port |
|---|---|
| Web UI | http://localhost:16686 |
| OTLP HTTP receiver | `localhost:4418` |
| OTLP gRPC receiver | `localhost:4417` |

Stop it with `docker-compose down`.

## Why the ports aren't 4318 / 4317

4318 (HTTP) and 4317 (gRPC) are the OpenTelemetry defaults, and every demo
in this repo points at `4418`/`4417` instead — on purpose.

Plenty of developer machines already have *something* listening on
`127.0.0.1:4318` — a local telemetry/observability agent, another demo
stack, an IDE plugin — that accepts the OTLP payload, replies `HTTP 200`,
and quietly discards it. If this collector also bound the default port,
your spans would appear to send successfully while actually landing in
whichever process claimed the port first, and you'd see nothing in Jaeger
with no error anywhere to explain why.

Remapping to `4418`/`4417` means a demo that successfully connects here is
*only* talking to this Jaeger instance — there's nothing else on your
machine it could be silently colliding with. Each demo's `.env.example`
already points at `4418` for you; you shouldn't need to change it for the
local-mode path.

If you deliberately want to point a demo at a different local OTLP
endpoint (e.g. your own collector), just edit that one line in its `.env`.
