"""Harness SDK + Anthropic GenAI tracing demo: support-ticket triage.

Diffed against `1-harness-sdk/openai/main.py`, the canonical Family A
reference implementation in this repo. Same STEP 1-6 structure, same
three-call scenario -- adapted for the Anthropic Python SDK's request/
response shape. See README.md for the full walkthrough.

Run:
    cp .env.example .env    # edit HARNESS_ACCOUNT_ID / HARNESS_REPORTING_TOKEN only
                             # if you're switching TRACE_TARGET to "harness"
    uv sync

    # In a separate terminal, leave this running (or set a real
    # ANTHROPIC_API_KEY instead and skip it):
    uv run ../../mock-providers/mock_anthropic_server.py

    # Back in this terminal:
    uv run main.py

Unlike openai/, there's no Ollama-equivalent local runtime for Anthropic's
Messages API -- but .env.example ships pointed at mock-providers/'s stub
server by default, so no real ANTHROPIC_API_KEY is needed to see a trace.
See README.md "Prerequisites".
"""
import os

from dotenv import load_dotenv
from opentelemetry import trace

# =====================================================================
# STEP 1 -- Configure via environment, before any other import.
#
# Every var this script or the SDK reads (TRACE_TARGET, HARNESS_*,
# ANTHROPIC_*, INGEST_BASE, LOCAL_OTLP_ENDPOINT) must be set before
# harness_sdk or anthropic are imported below -- the SDK reads its
# HARNESS_* config at instrument() time, not lazily.
# =====================================================================
load_dotenv()  # populates os.environ from .env; no-op if .env is absent

TRACE_TARGET = os.environ.get("TRACE_TARGET", "local")

os.environ["HARNESS_SERVICE_NAME"] = "cacm-demo-anthropic"

# Instrumentation is opt-in per provider -- nothing is patched unless this
# is set, even after instrument() is called. Note the provider suffix:
# AI_ANTHROPIC here, not AI_OPENAI.
os.environ["HARNESS_ENABLE_AI_ANTHROPIC"] = "true"

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
# support ticket, triaged in three calls. Identical ticket text to
# openai/, so the two apps' traces are directly comparable.
# =====================================================================
SUPPORT_TICKET = (
    "Subject: Checkout is broken for all EU customers\n\n"
    "Since this morning's deploy, every customer in the EU region gets a "
    "500 error at the final payment step. US customers are unaffected. "
    "This is blocking all EU revenue and support is getting flooded with "
    "tickets."
)

# Anthropic tool schemas use "input_schema", not OpenAI's nested
# {"type": "function", "function": {..., "parameters": ...}} shape.
CLASSIFY_TOOL = {
    "name": "classify_severity",
    "description": "Classify the severity of a support ticket.",
    "input_schema": {
        "type": "object",
        "properties": {
            "severity": {
                "type": "string",
                "enum": ["low", "medium", "high", "critical"],
            },
        },
        "required": ["severity"],
    },
}


def run():
    # =================================================================
    # STEP 2 -- Instrument BEFORE importing the provider client.
    #
    # agent.instrument() monkey-patches the Anthropic client class at
    # import time. If `import anthropic` runs before this call, the patch
    # has nothing left to attach to and every span is silently dropped --
    # no error, no warning.
    # =================================================================
    agent = Agent()
    agent.instrument()

    # =================================================================
    # STEP 3 -- Import the provider client, only after instrument() (see
    # STEP 2). Kept inside this function body, not at module level, so
    # the ordering can't be accidentally broken by a future edit that
    # hoists imports to the top of the file.
    # =================================================================
    import anthropic  # noqa: E402  (deliberately imported AFTER instrument())

    client = anthropic.Anthropic(
        # There's no Ollama-equivalent local runtime for Anthropic's
        # Messages API to point at (see README "Prerequisites"), so
        # .env.example ships this pointed at mock-providers/'s stub
        # /v1/messages server by default -- see
        # mock-providers/mock_anthropic_server.py and mock-providers/README.md.
        # Clear ANTHROPIC_BASE_URL and set a real ANTHROPIC_API_KEY to use
        # the real Anthropic API instead.
        base_url=os.environ.get("ANTHROPIC_BASE_URL") or None,
        api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
    )
    model = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")

    # =================================================================
    # STEP 4 -- Run the scenario: support-ticket triage, three calls.
    # temperature=0 and a tight max_tokens on every call --
    # this is a demo, not a benchmark; a full run costs well under $0.01
    # against the real Anthropic API.
    #
    # All three calls run inside one manually-created parent span. Without
    # it, they'd land as three unrelated root traces, not a waterfall:
    # anthropic's auto-instrumentation opens and closes each "chat" span
    # entirely inside its own messages.create() call (verified against
    # harness_sdk's anthropic instrumentor -- handler.start_llm/stop_llm
    # both run inside the wrapped call, nothing survives past its return),
    # so there's no span still current either between calls or after the
    # last one returns for these three to attach to. The wrapper span
    # below is also what makes STEP 5's set_span_attribute call work --
    # see the note there.
    # =================================================================
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("support_ticket_triage"):
        print(f"\n--- Ticket ---\n{SUPPORT_TICKET}\n", flush=True)

        # Call 1: classify severity via a forced tool call. Anthropic expresses
        # "force this exact tool" as tool_choice={"type": "tool", "name": ...},
        # not OpenAI's {"type": "function", "function": {"name": ...}}.
        classify_response = client.messages.create(
            model=model,
            max_tokens=50,
            system="Classify the ticket's severity by calling classify_severity.",
            messages=[{"role": "user", "content": SUPPORT_TICKET}],
            tools=[CLASSIFY_TOOL],
            tool_choice={"type": "tool", "name": "classify_severity"},
            # anthropic>=1.x removed temperature/top_p/top_k as named
            # messages.create() kwargs entirely (TypeError if passed directly).
            # Haiku 4.5 still honors temperature at the API level, and this demo
            # relies on temperature=0 for deterministic output, so it goes into
            # extra_body instead of being dropped.
            extra_body={"temperature": 0},
        )
        # Tool-use response blocks arrive in `content` as items with
        # type="tool_use", whose `.input` is already a parsed dict -- unlike
        # OpenAI's tool_calls[].function.arguments, which is a JSON string
        # requiring json.loads(). No JSON parsing step needed here.
        tool_use_block = next(
            block for block in classify_response.content if block.type == "tool_use"
        )
        severity = tool_use_block.input["severity"]
        print(f"Severity: {severity}", flush=True)

        # Call 2: summarize the ticket, a short completion. Anthropic's `system`
        # is a top-level request param, not a "system" message inside `messages`.
        summarize_response = client.messages.create(
            model=model,
            max_tokens=60,
            system="Summarize the support ticket in one sentence.",
            messages=[{"role": "user", "content": SUPPORT_TICKET}],
            extra_body={"temperature": 0},  # see Call 1 comment
        )
        summary = summarize_response.content[0].text
        print(f"Summary: {summary}", flush=True)

        # Call 3: draft a customer reply -- multi-turn, uses calls 1+2 as
        # context, so token usage grows across the three spans. Prior turns
        # are threaded through `messages` exactly like OpenAI's chat history;
        # only `system` moves out to the top-level param.
        reply_response = client.messages.create(
            model=model,
            max_tokens=120,
            system="Draft a brief, empathetic customer-facing reply.",
            messages=[
                {"role": "user", "content": SUPPORT_TICKET},
                {"role": "assistant", "content": f"Severity: {severity}. Summary: {summary}"},
                {"role": "user", "content": "Draft the reply to the customer now."},
            ],
            extra_body={"temperature": 0},  # see Call 1 comment
        )
        draft_reply = reply_response.content[0].text
        print(f"\nDraft reply:\n{draft_reply}\n", flush=True)

        # =============================================================
        # STEP 5 -- Enrich the current span with a custom business
        # attribute. "Current" here is the support_ticket_triage span
        # opened above, not one of the three auto-created "chat" spans --
        # each of those has already ended by the time its own
        # messages.create() call returns, so nothing set after any of
        # them would land anywhere (set_span_attribute silently no-ops
        # with no recording span current; see harness_sdk's own docs on
        # it). Staying inside this `with` block is what makes this call
        # actually take effect.
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
