#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Minimal OpenAI-compatible /v1/chat/completions stub.

Stands in for a real OpenAI account (or a local Ollama instance) so
1-harness-sdk/openai/'s, 3-manual-instrumentation/python/'s, and
2-open-source-sdks/litellm-proxy/'s three support-ticket-triage calls can
run with no provider credentials at all -- see each app's README.md
"Prerequisites"/Setup for how to point it at this server. Also used by
.github/workflows/ci.yml, unmodified, so this is the exact same stub a
customer would run locally, not a separate CI-only fixture. Stdlib-only
(http.server); the PEP 723 block above lets `uv run` execute it in its own
throwaway environment, independent of any app's pyproject.toml/uv.lock and
with no separate python3 install needed.

Canned responses only -- this exercises the OTel instrumentation pipeline
(spans, gen_ai.* attributes) end to end, it does not produce real model
output or realistic token counts. Switch back to a real key (or Ollama)
once you've confirmed spans show up in Jaeger.

Response shape matches the OpenAI Chat Completions API closely enough for
opentelemetry-instrumentation-openai_v2 to populate gen_ai.request.model
and gen_ai.usage.* from it. A request gets a tool-call response iff it
carries "tool_choice" -- that's main.py's call 1, which forces
classify_severity via tool_choice; calls 2 and 3 have no tool_choice and
get a plain text completion.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

# 0.0.0.0, not 127.0.0.1: litellm-proxy's CI job reaches this server from
# inside a container via host.docker.internal:host-gateway, which on
# native Linux Docker Engine (GitHub's ubuntu-latest runners) is a real
# bridge-gateway IP, not a loopback alias -- a socket bound to 127.0.0.1
# silently refuses traffic arriving on that interface. The other two CI
# jobs that reuse this script (1-harness-sdk/openai, 3-manual-
# instrumentation/python) run the app directly on the runner and connect
# over 127.0.0.1 either way, so this is a strict widening, not a behavior
# change for them.
HOST = "0.0.0.0"
PORT = 8080


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/healthz":
            self._send_json({"status": "ok"})
        else:
            self._send_json({"error": "not found"}, status=404)

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self._send_json({"error": "not found"}, status=404)
            return

        length = int(self.headers.get("Content-Length", 0))
        request = json.loads(self.rfile.read(length) or b"{}")
        model = request.get("model", "mock-model")

        if request.get("tool_choice"):
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_mock_classify",
                        "type": "function",
                        "function": {
                            "name": "classify_severity",
                            "arguments": json.dumps({"severity": "critical"}),
                        },
                    }
                ],
            }
            finish_reason = "tool_calls"
        else:
            message = {
                "role": "assistant",
                "content": "This is a stubbed CI response for the demo scenario.",
            }
            finish_reason = "stop"

        self._send_json(
            {
                "id": "chatcmpl-mock",
                "object": "chat.completion",
                "created": 0,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": finish_reason,
                    }
                ],
                "usage": {
                    "prompt_tokens": 42,
                    "completion_tokens": 8,
                    "total_tokens": 50,
                },
            }
        )

    def log_message(self, format, *args):
        sys.stderr.write("[mock-openai] " + (format % args) + "\n")


if __name__ == "__main__":
    HTTPServer((HOST, PORT), Handler).serve_forever()
