"""Harness SDK + OpenAI GenAI tracing demo: support-ticket triage.

The canonical Family A (Harness SDK) reference implementation in this repo
-- every other `1-harness-sdk/*` app is a diff against this one. See
README.md for the full walkthrough.

Run:
    cp .env.example .env    # edit HARNESS_ACCOUNT_ID / HARNESS_REPORTING_TOKEN only
                             # if you're switching TRACE_TARGET to "harness"
    uv sync

    # In a separate terminal, leave this running (or point .env at a
    # local Ollama instance or a real OPENAI_API_KEY instead and skip
    # it -- see .env.example):
    uv run ../../mock-providers/mock_openai_server.py

    # Back in this terminal:
    uv run main.py

TRACE_TARGET=local (the default) needs no Harness account, no Harness
token, and -- with the shipped mock-server defaults -- no OpenAI account
either.
"""
import json
import os

from dotenv import load_dotenv
from opentelemetry import trace

# =====================================================================
# STEP 1 -- Configure via environment, before any other import.
#
# Every var this script or the SDK reads (TRACE_TARGET, HARNESS_*,
# OPENAI_*, INGEST_BASE, LOCAL_OTLP_ENDPOINT) must be set before
# harness_sdk or openai are imported below -- the SDK reads its
# HARNESS_* config at instrument() time, not lazily.
# =====================================================================
load_dotenv()  # populates os.environ from .env; no-op if .env is absent

TRACE_TARGET = os.environ.get("TRACE_TARGET", "local")

os.environ["HARNESS_SERVICE_NAME"] = "cacm-demo-openai"

# Instrumentation is opt-in per provider -- nothing is patched unless this
# is set, even after instrument() is called.
os.environ["HARNESS_ENABLE_AI_OPENAI"] = "true"

# Prompt/response text capture stays off in every demo in this repo.
os.environ["HARNESS_GEN_AI_PAYLOAD_CAPTURE_ENABLED"] = "false"

# HARNESS_ENABLE_CONSOLE_SPAN_EXPORTER is EXCLUSIVE with OTLP export, not
# additive to it: turning it on replaces the export path configured below
# with stdout-only span dumps, it doesn't supplement it. Every demo in this
# repo ships it "false" for that reason. Flip it to "true" only to eyeball
# span JSON on stdout, and expect nothing to reach Jaeger/CACM while it's on.
os.environ["HARNESS_ENABLE_CONSOLE_SPAN_EXPORTER"] = "false"

if TRACE_TARGET == "harness":
    account_id = os.environ["HARNESS_ACCOUNT_ID"]
    os.environ["HARNESS_REPORTING_TOKEN"]  # fail fast if unset, rather than silently exporting with no auth header
    ingest_base = os.environ.get("INGEST_BASE", "https://prod3.harness.io/udp-ingest")

    os.environ["HARNESS_REPORTING_TRACE_REPORTER_TYPE"] = "OTLP_HTTP"
    os.environ["HARNESS_REPORTING_ENDPOINT"] = (
        f"{ingest_base}/otel/v1/traces"
        f"?accountIdentifier={account_id}&routingId={account_id}"
    )
    # Optional when x-harness-service-token is present (the gateway derives
    # the account from the token) -- but if set, it must match the token's
    # account exactly, or ingestion fails with a hard 403 "tenant mismatch".
    # Both this and HARNESS_REPORTING_TOKEN come from HARNESS_ACCOUNT_ID/
    # .env, so there's one place to get the account ID wrong, not two.
    os.environ["HARNESS_RESOURCE_ATTRIBUTES"] = f"harness.account.id={account_id}"

    # HARNESS_REPORTING_TOKEN is the SDK's native auth path: the exporter
    # sends it as the x-harness-service-token header automatically (see
    # otel-python-sdk's agent_init.py). An ordinary personal/service-account
    # token gets the same tenant-check enforcement as any other credential --
    # this is not an admin/cross-account bypass (verified against a live
    # gateway and confirmed by the platform/UDP team; see
    # docs/01-get-your-token.md). No manual OTEL_EXPORTER_OTLP_HEADERS
    # needed for this path.
else:
    # local-collector/'s Jaeger. Port 4418, not the OTel default 4318:
    # many machines run a local telemetry agent bound to 127.0.0.1:4318
    # that answers HTTP 200 and silently discards whatever is sent to it.
    local_endpoint = os.environ.get("LOCAL_OTLP_ENDPOINT", "http://localhost:4418")
    os.environ["HARNESS_REPORTING_TRACE_REPORTER_TYPE"] = "OTLP_HTTP"
    os.environ["HARNESS_REPORTING_ENDPOINT"] = f"{local_endpoint}/v1/traces"

from harness_sdk.agent import Agent  # noqa: E402
from harness_sdk import set_span_attribute  # noqa: E402

# =====================================================================
# STEP 4 material -- the shared demo scenario (LLD §7): one hard-coded
# support ticket, triaged in three calls.
# =====================================================================
SUPPORT_TICKET = (
    "Subject: Checkout is broken for all EU customers\n\n"
    "Since this morning's deploy, every customer in the EU region gets a "
    "500 error at the final payment step. US customers are unaffected. "
    "This is blocking all EU revenue and support is getting flooded with "
    "tickets."
)

CLASSIFY_TOOL = {
    "type": "function",
    "function": {
        "name": "classify_severity",
        "description": "Classify the severity of a support ticket.",
        "parameters": {
            "type": "object",
            "properties": {
                "severity": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "critical"],
                },
            },
            "required": ["severity"],
        },
    },
}


def run():
    # =================================================================
    # STEP 2 -- Instrument BEFORE importing the provider client.
    #
    # agent.instrument() monkey-patches the OpenAI client class at import
    # time. If `import openai` runs before this call, the patch has
    # nothing left to attach to and every span is silently dropped -- no
    # error, no warning.
    # =================================================================
    agent = Agent()
    agent.instrument()

    # =================================================================
    # STEP 3 -- Import the provider client, only after instrument() (see
    # STEP 2). Kept inside this function body, not at module level, so
    # the ordering can't be accidentally broken by a future edit that
    # hoists imports to the top of the file.
    # =================================================================
    import openai  # noqa: E402  (deliberately imported AFTER instrument())

    client = openai.OpenAI(
        base_url=os.environ.get("OPENAI_BASE_URL") or None,
        api_key=os.environ.get("OPENAI_API_KEY", ""),
    )
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    # =================================================================
    # STEP 4 -- Run the scenario: support-ticket triage, three calls.
    # temperature=0 and a tight max_tokens on every call --
    # this is a demo, not a benchmark; a full run costs well under $0.01
    # against the real OpenAI API, and nothing at all against Ollama.
    #
    # All three calls run inside one manually-created parent span. Without
    # it, they'd land as three unrelated root traces, not a waterfall:
    # openai's auto-instrumentation opens and closes each "chat" span
    # entirely inside its own chat.completions.create() call (verified
    # against harness_sdk's openai instrumentor -- handler.start_llm/
    # stop_llm both run inside the wrapped call, nothing survives past its
    # return), so there's no span still current either between calls or
    # after the last one returns for these three to attach to. The
    # wrapper span below is also what makes STEP 5's set_span_attribute
    # call work -- see the note there.
    # =================================================================
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("support_ticket_triage"):
        print(f"\n--- Ticket ---\n{SUPPORT_TICKET}\n", flush=True)

        # Call 1: classify severity via a forced tool call (structured output).
        classify_response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "Classify the ticket's severity by calling classify_severity.",
                },
                {"role": "user", "content": SUPPORT_TICKET},
            ],
            tools=[CLASSIFY_TOOL],
            tool_choice={"type": "function", "function": {"name": "classify_severity"}},
            temperature=0,
            max_tokens=50,
        )
        tool_call = classify_response.choices[0].message.tool_calls[0]
        severity = json.loads(tool_call.function.arguments)["severity"]
        print(f"Severity: {severity}", flush=True)

        # Call 2: summarize the ticket, a short completion.
        summarize_response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Summarize the support ticket in one sentence."},
                {"role": "user", "content": SUPPORT_TICKET},
            ],
            temperature=0,
            max_tokens=60,
        )
        summary = summarize_response.choices[0].message.content
        print(f"Summary: {summary}", flush=True)

        # Call 3: draft a customer reply -- multi-turn, uses calls 1+2 as
        # context, so token usage grows across the three spans.
        reply_response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Draft a brief, empathetic customer-facing reply."},
                {"role": "user", "content": SUPPORT_TICKET},
                {"role": "assistant", "content": f"Severity: {severity}. Summary: {summary}"},
                {"role": "user", "content": "Draft the reply to the customer now."},
            ],
            temperature=0,
            max_tokens=120,
        )
        draft_reply = reply_response.choices[0].message.content
        print(f"\nDraft reply:\n{draft_reply}\n", flush=True)

        # =============================================================
        # STEP 5 -- Enrich the current span with a custom business
        # attribute. "Current" here is the support_ticket_triage span
        # opened above, not one of the three auto-created "chat" spans --
        # each of those has already ended by the time its own
        # chat.completions.create() call returns, so nothing set after
        # any of them would land anywhere (set_span_attribute silently
        # no-ops with no recording span current; see harness_sdk's own
        # docs on it). Staying inside this `with` block is what makes
        # this call actually take effect.
        # =============================================================
        set_span_attribute("custom.ticket_severity", severity)

    # =================================================================
    # STEP 6 -- Flush before exit.
    #
    # The OTLP exporter batches spans (default flush interval: 5s) and
    # the SDK registers no atexit hook to flush on process exit. Without
    # this explicit call, a short-lived script like this one can exit
    # before its spans are ever sent, and they're silently dropped.
    # =================================================================
    print("[OTel] Flushing spans...", flush=True)
    trace.get_tracer_provider().force_flush()


if __name__ == "__main__":
    run()
