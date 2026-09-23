#!/usr/bin/env python3
"""Minimal Vertex AI generateContent stub, for CI (and local testing without
Google Cloud / ADC).

Stands in for a real Vertex AI project so
1-harness-sdk/google-genai-vertex/main.py's three support-ticket-triage
calls can run with no Google Cloud credentials at all. Stdlib-only
(http.server) so it runs under the system python3, outside any app's
uv-managed venv -- no dependency on the app's pyproject.toml/uv.lock.

Unlike openai/'s and anthropic/'s mocks, this isn't reached via a
provider-specific *_BASE_URL env var pointing at an OpenAI-/Anthropic-
compatible endpoint -- there's no such thing for Vertex AI. main.py
reaches this stub via GOOGLE_GENAI_BASE_URL, which it turns into
http_options={"base_url": ..., "base_url_resource_scope": "COLLECTION"}
on the google-genai Client. That combination (verified against the SDK
source, google-genai>=1.55.0) makes the client skip Application Default
Credentials entirely and send an unauthenticated request straight here,
with a path shaped like ".../publishers/google/models/<model>:generateContent"
-- no "projects/{project}/locations/{location}/" prefix, since no
project/location is passed alongside the base_url override. This handler
matches on the ":generateContent" suffix rather than an exact path for
that reason, and pulls the model name out of the path itself rather than
the request body, since the wire request body has no "model" field of its
own (it's encoded in the URL).

Response shape matches the Vertex AI generateContent response closely
enough for harness_sdk's google-genai instrumentor to populate
gen_ai.request.model and gen_ai.usage.* from it. A request gets a
functionCall response iff its body carries "toolConfig" -- that's main.py's
call 1, which forces classify_severity via tool_config/mode="ANY"; calls 2
and 3 have no toolConfig and get a plain text response.
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
        if ":generateContent" not in self.path:
            self._send_json({"error": "not found"}, status=404)
            return

        # Path looks like ".../publishers/google/models/<model>:generateContent"
        # (or, for the Gemini Developer API shape, "models/<model>:generateContent")
        # -- the model name is the last path segment, before the colon.
        last_segment = self.path.rsplit("/", 1)[-1]
        model = last_segment.split(":generateContent")[0]

        length = int(self.headers.get("Content-Length", 0))
        request = json.loads(self.rfile.read(length) or b"{}")

        if request.get("toolConfig"):
            content = {
                "role": "model",
                "parts": [
                    {
                        "functionCall": {
                            "name": "classify_severity",
                            "args": {"severity": "critical"},
                        }
                    }
                ],
            }
        else:
            content = {
                "role": "model",
                "parts": [
                    {"text": "This is a stubbed CI response for the demo scenario."}
                ],
            }

        self._send_json(
            {
                "candidates": [
                    {
                        "content": content,
                        "finishReason": "STOP",
                    }
                ],
                "modelVersion": model,
                "responseId": "resp_mock",
                "usageMetadata": {
                    "promptTokenCount": 42,
                    "candidatesTokenCount": 8,
                    "totalTokenCount": 50,
                },
            }
        )

    def log_message(self, format, *args):
        sys.stderr.write("[mock-google-genai] " + (format % args) + "\n")


if __name__ == "__main__":
    HTTPServer((HOST, PORT), Handler).serve_forever()
