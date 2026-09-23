#!/usr/bin/env bash
# The same three-call support-ticket-triage scenario every app in this
# repo runs (classify severity, summarize, draft a reply -- see repo root
# README.md), sent as three curl calls against the proxy started by
# `docker-compose up -d`, instead of a Python script's three SDK calls.
#
# All three calls carry the same W3C traceparent trace-id (TRACE_ID
# below), so they land in Jaeger as one trace with three spans, the same
# single-trace shape every 1-harness-sdk/* app's main.py produces -- just
# achieved by the caller propagating trace context on each request instead
# of a manually-created parent span held open in a long-lived process
# (there's no process here to hold one open across all three calls).
#
# Requires curl, jq, and openssl -- all present by default on the GitHub
# Actions runner this also runs under in CI; on macOS, `brew install jq`
# if you don't already have it.
set -euo pipefail

PROXY_URL="${PROXY_URL:-http://localhost:4000}"
MODEL="support-ticket-triage"

TRACE_ID=$(openssl rand -hex 16)
PARENT_SPAN_ID=$(openssl rand -hex 8)
TRACEPARENT="00-${TRACE_ID}-${PARENT_SPAN_ID}-01"

TICKET="Subject: Checkout is broken for all EU customers
Body: Since this morning's deploy, EU customers get a 500 error at
checkout. This is blocking revenue and affecting all EU traffic."

chat() {
  curl -sf "$PROXY_URL/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -H "traceparent: $TRACEPARENT" \
    -d "$1"
}

echo "--- Ticket ---"
echo "$TICKET"
echo

echo "Call 1 -- classify severity (tool call)"
CALL1_PAYLOAD=$(jq -n --arg model "$MODEL" --arg ticket "$TICKET" '{
  model: $model,
  temperature: 0,
  max_tokens: 50,
  messages: [
    {role: "system", content: "Classify the support ticket severity."},
    {role: "user", content: $ticket}
  ],
  tools: [{
    type: "function",
    function: {
      name: "classify_severity",
      description: "Record the ticket severity",
      parameters: {
        type: "object",
        properties: {
          severity: {type: "string", enum: ["low", "medium", "high", "critical"]}
        },
        required: ["severity"]
      }
    }
  }],
  tool_choice: {type: "function", function: {name: "classify_severity"}}
}')
CALL1_RESPONSE=$(chat "$CALL1_PAYLOAD")
SEVERITY=$(echo "$CALL1_RESPONSE" | jq -r '.choices[0].message.tool_calls[0].function.arguments' | jq -r '.severity')
echo "Severity: $SEVERITY"
echo

echo "Call 2 -- summarize the ticket"
CALL2_PAYLOAD=$(jq -n --arg model "$MODEL" --arg ticket "$TICKET" '{
  model: $model,
  temperature: 0,
  max_tokens: 100,
  messages: [
    {role: "system", content: "Summarize the support ticket in one sentence."},
    {role: "user", content: $ticket}
  ]
}')
CALL2_RESPONSE=$(chat "$CALL2_PAYLOAD")
SUMMARY=$(echo "$CALL2_RESPONSE" | jq -r '.choices[0].message.content')
echo "Summary: $SUMMARY"
echo

echo "Call 3 -- draft a customer reply (uses calls 1+2 as context)"
CALL3_PAYLOAD=$(jq -n \
  --arg model "$MODEL" \
  --arg ticket "$TICKET" \
  --arg severity "$SEVERITY" \
  --arg summary "$SUMMARY" \
  '{
    model: $model,
    temperature: 0,
    max_tokens: 150,
    messages: [
      {role: "system", content: "Draft a short customer reply acknowledging the issue."},
      {role: "user", content: $ticket},
      {role: "assistant", content: ("Severity: " + $severity)},
      {role: "assistant", content: ("Summary: " + $summary)}
    ]
  }')
CALL3_RESPONSE=$(chat "$CALL3_PAYLOAD")
DRAFT_REPLY=$(echo "$CALL3_RESPONSE" | jq -r '.choices[0].message.content')

echo "Draft reply:"
echo "$DRAFT_REPLY"
echo

echo "Trace ID: $TRACE_ID"
echo "Open http://localhost:16686, service cacm-demo-litellm-proxy, and search by this trace ID -- see README.md \"What to look for.\""
