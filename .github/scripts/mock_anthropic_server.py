#!/usr/bin/env python3
"""Minimal Anthropic-compatible /v1/messages stub, for CI (and local testing
without an Anthropic API key).

Stands in for a real Anthropic account so 1-harness-sdk/anthropic/main.py's
three support-ticket-triage calls can run with no provider credentials.
Stdlib-only (http.server) so it runs under the system python3, outside any
app's uv-managed venv -- no dependency on the app's pyproject.toml/uv.lock.

Unlike openai/'s mock (mock_openai_server.py), there's no local runtime
(Ollama-equivalent) this stands in for -- Anthropic's Messages API has no
OpenAI-compatible mode to fall back to. This stub exists purely to exercise
the OTel instrumentation pipeline (spans, gen_ai.* attributes) end to end;
it proves the plumbing works, not real model output.

Response shape matches the Anthropic Messages API closely enough for
opentelemetry-instrumentation-anthropic to populate gen_ai.request.model
and gen_ai.usage.* from it. A request gets a tool_use response iff it
carries "tool_choice" -- that's main.py's call 1, which forces
classify_severity via tool_choice; calls 2 and 3 have no tool_choice and
get a plain text response.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

HOST = "127.0.0.1"
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
        if self.path != "/v1/messages":
            self._send_json({"error": "not found"}, status=404)
            return

        length = int(self.headers.get("Content-Length", 0))
        request = json.loads(self.rfile.read(length) or b"{}")
        model = request.get("model", "mock-model")

        if request.get("tool_choice"):
            content = [
                {
                    "type": "tool_use",
                    "id": "toolu_mock_classify",
                    "name": "classify_severity",
                    "input": {"severity": "critical"},
                }
            ]
            stop_reason = "tool_use"
        else:
            content = [
                {
                    "type": "text",
                    "text": "This is a stubbed CI response for the demo scenario.",
                }
            ]
            stop_reason = "end_turn"

        self._send_json(
            {
                "id": "msg_mock",
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": content,
                "stop_reason": stop_reason,
                "stop_sequence": None,
                "usage": {
                    "input_tokens": 42,
                    "output_tokens": 8,
                },
            }
        )

    def log_message(self, format, *args):
        sys.stderr.write("[mock-anthropic] " + (format % args) + "\n")


if __name__ == "__main__":
    HTTPServer((HOST, PORT), Handler).serve_forever()
