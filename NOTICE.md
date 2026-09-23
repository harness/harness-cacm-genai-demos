# NOTICE

## harness-cacm-genai-demos

Copyright 2026 Harness, Inc.

Licensed under the Apache License, Version 2.0. See [LICENSE.md](LICENSE.md)
for the full license text.

## Third-party software

This repository does not vendor or bundle any third-party source code. Each
demo folder only *depends on* the packages below — declared in that folder's
own `pyproject.toml`/`uv.lock` (or `docker-compose.yaml`/`config.yaml` for
`2-open-source-sdks/litellm-proxy/`, which has no Python package of its own)
and resolved from PyPI / a container registry at setup time, never copied
into this repo. Listed here for attribution, not because their code ships
with it:

| Project | License | Source |
|---|---|---|
| OpenTelemetry Python SDK | Apache-2.0 | https://github.com/open-telemetry/opentelemetry-python |
| `opentelemetry-instrumentation-anthropic` | Apache-2.0 | https://github.com/open-telemetry/opentelemetry-python-contrib |
| `opentelemetry-util-genai` | Apache-2.0 | https://github.com/open-telemetry/opentelemetry-python-contrib |
| OpenAI Python SDK | Apache-2.0 | https://github.com/openai/openai-python |
| Anthropic Python SDK | MIT | https://github.com/anthropics/anthropic-sdk-python |
| LiteLLM | MIT | https://github.com/BerriAI/litellm |
| Google Gen AI Python SDK | Apache-2.0 | https://github.com/googleapis/python-genai |
| httpx | BSD-3-Clause | https://github.com/encode/httpx |
| python-dotenv | BSD-3-Clause | https://github.com/theskumar/python-dotenv |
| Jaeger (container image, `local-collector/` and `2-open-source-sdks/litellm-proxy/`) | Apache-2.0 | https://github.com/jaegertracing/jaeger |
| `harness-sdk` | Apache-2.0 | https://github.com/harness/otel-python-sdk |

Each project remains under its own copyright and license; this list does not
relicense them. See each project's own repository for its full license text
and copyright notices.
