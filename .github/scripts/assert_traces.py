#!/usr/bin/env python3
"""Assert exported span count and gen_ai.* attribute keys via Jaeger's JSON API.

Polls Jaeger's query API (http://localhost:16686/api/traces?service=...)
because main.py's STEP 6 force_flush() returns as soon as the export HTTP
call is made, not once Jaeger has finished ingesting and indexing it.
Once the expected span count is seen, checks that every span whose
operationName starts with --gen-ai-operation-prefix (default: "", i.e.
every span) carries the gen_ai.* attributes this demo's README documents
in "What to look for". The prefix exists for apps like
google-genai-vertex, whose main.py wraps its provider calls in one
manually-created parent span that carries no gen_ai.* attributes of its
own -- passing --gen-ai-operation-prefix "chat " excludes that wrapper
span from the per-span key check while still counting it towards
--expected-spans.

--gen-ai-provider-key overrides which key identifies the provider
(default: gen_ai.provider.name, what every harness-sdk instrumentor
emits). litellm-proxy's built-in otel callback predates that
semantic-convention name and emits gen_ai.system instead -- its CI job
passes --gen-ai-provider-key gen_ai.system.
"""
import argparse
import json
import sys
import time
import urllib.request

REQUIRED_GEN_AI_KEYS = {
    "gen_ai.request.model",
    "gen_ai.usage.input_tokens",
    "gen_ai.usage.output_tokens",
}


def fetch_spans(service, jaeger_url):
    url = f"{jaeger_url}/api/traces?service={service}&limit=50"
    with urllib.request.urlopen(url, timeout=10) as response:
        payload = json.load(response)
    spans = []
    for trace in payload.get("data", []):
        spans.extend(trace.get("spans", []))
    return spans


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", required=True)
    parser.add_argument("--expected-spans", type=int, required=True)
    parser.add_argument("--jaeger-url", default="http://localhost:16686")
    parser.add_argument("--retries", type=int, default=20)
    parser.add_argument("--retry-delay", type=float, default=1.0)
    parser.add_argument("--gen-ai-operation-prefix", default="")
    parser.add_argument(
        "--gen-ai-provider-key",
        default="gen_ai.provider.name",
        help=(
            "Attribute key that identifies the provider (e.g. 'openai'). "
            "Every harness-sdk instrumentor emits gen_ai.provider.name; "
            "litellm-proxy's built-in otel callback predates that "
            "semantic-convention name and emits gen_ai.system instead."
        ),
    )
    args = parser.parse_args()
    required_keys = REQUIRED_GEN_AI_KEYS | {args.gen_ai_provider_key}

    spans = []
    for attempt in range(args.retries):
        try:
            spans = fetch_spans(args.service, args.jaeger_url)
        except Exception as exc:
            print(f"[assert-traces] fetch attempt {attempt + 1} failed: {exc}")
            spans = []
        if len(spans) >= args.expected_spans:
            break
        time.sleep(args.retry_delay)

    if len(spans) != args.expected_spans:
        print(
            f"[assert-traces] expected {args.expected_spans} spans for "
            f"service={args.service!r}, found {len(spans)}",
            file=sys.stderr,
        )
        sys.exit(1)

    for span in spans:
        if not span.get("operationName", "").startswith(args.gen_ai_operation_prefix):
            continue
        tag_keys = {tag["key"] for tag in span.get("tags", [])}
        missing = required_keys - tag_keys
        if missing:
            print(
                f"[assert-traces] span {span.get('operationName')!r} "
                f"missing required gen_ai.* keys: {sorted(missing)}",
                file=sys.stderr,
            )
            sys.exit(1)

    print(
        f"[assert-traces] OK: {len(spans)} spans for service={args.service!r}, "
        f"all carry {sorted(required_keys)}"
    )


if __name__ == "__main__":
    main()
