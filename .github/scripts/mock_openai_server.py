#!/usr/bin/env python3
"""Minimal OpenAI-compatible /v1/chat/completions stub, for CI only.

Stands in for a real OpenAI account (or a local Ollama instance) so
1-harness-sdk/openai/main.py's three support-ticket-triage calls can run
in CI with no provider credentials. Stdlib-only (http.server) so it runs
under the runner's system python3, outside any app's uv-managed venv --
no dependency on the app's pyproject.toml/uv.lock.

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
