"""Harness SDK + LiteLLM GenAI tracing demo: support-ticket triage.

Diffed against `1-harness-sdk/anthropic/main.py`: same STEP 1-6 structure,
same three-call scenario, same default underlying model
(claude-haiku-4-5) -- but called through `litellm.completion()` instead
of the Anthropic Python SDK directly, via LiteLLM's model-string routing
(`LITELLM_MODEL=anthropic/claude-haiku-4-5`). LiteLLM normalizes both the
request shape (OpenAI-style `tools`/`tool_choice`, not Anthropic's
`input_schema`) and the response shape (an OpenAI `ModelResponse`, not
Anthropic's `content` blocks) regardless of which provider is behind the
model string. See README.md "What to look for" for what this normalization
means for token counts specifically.

Run:
    cp .env.example .env    # edit HARNESS_ACCOUNT_ID / HARNESS_REPORTING_TOKEN only
                             # if you're switching TRACE_TARGET to "harness"
    uv sync
    uv run main.py

Like anthropic/, there's no local zero-cost provider path here -- LiteLLM
still needs a real ANTHROPIC_API_KEY to reach the Anthropic API, even when
TRACE_TARGET=local. See README.md "Prerequisites".
"""
import json
import os

from dotenv import load_dotenv
from opentelemetry import trace

# =====================================================================
# STEP 1 -- Configure via environment, before any other import.
#
# Every var this script or the SDK reads (TRACE_TARGET, HARNESS_*,
# ANTHROPIC_API_KEY, LITELLM_*, INGEST_BASE, LOCAL_OTLP_ENDPOINT) must be
# set before harness_sdk or litellm are imported below -- the SDK reads
# its HARNESS_* config at instrument() time, not lazily.
# =====================================================================
load_dotenv()  # populates os.environ from .env; no-op if .env is absent

TRACE_TARGET = os.environ.get("TRACE_TARGET", "local")

os.environ["HARNESS_SERVICE_NAME"] = "cacm-demo-litellm"

# Instrumentation is opt-in per provider -- nothing is patched unless this
# is set, even after instrument() is called. Note the LiteLLM-specific
# flag: AI_LITELLM here, not AI_ANTHROPIC, even though the underlying
# calls in this app land on Anthropic's API -- the flag names the
# instrumentor (LiteLLM), not the provider it happens to route to.
os.environ["HARNESS_ENABLE_AI_LITELLM"] = "true"

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
# openai/ and anthropic/, so all three apps' traces are directly
# comparable.
# =====================================================================
SUPPORT_TICKET = (
    "Subject: Checkout is broken for all EU customers\n\n"
    "Since this morning's deploy, every customer in the EU region gets a "
    "500 error at the final payment step. US customers are unaffected. "
    "This is blocking all EU revenue and support is getting flooded with "
    "tickets."
)

# LiteLLM accepts OpenAI's nested tool-schema shape for every provider it
# routes to, including Anthropic -- unlike anthropic/main.py, which uses
# Anthropic's own flat "input_schema" shape directly against the Anthropic
# SDK. LiteLLM translates this into the wire format the target provider
# actually expects.
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
    # harness_sdk's LiteLLM instrumentor works differently from the
    # openai/anthropic ones: instead of patching a client *class* (so
    # ordering matters at instantiation time), agent.instrument() imports
    # litellm itself and rebinds its module-level functions (completion,
    # acompletion, ...) in place. This app's own `import litellm` below
    # still comes after instrument(), matching every other app in this
    # repo (LLD §12.1) -- keep it that way even though, for this specific
    # instrumentor, the ordering isn't the sole thing standing between you
    # and a dropped span the way it is for openai/anthropic.
    # =================================================================
    agent = Agent()
    agent.instrument()

    # =================================================================
    # STEP 3 -- Import litellm, only after instrument() (see STEP 2).
    # Kept inside this function body, not at module level, so the
    # ordering can't be accidentally broken by a future edit that hoists
    # imports to the top of the file.
    # =================================================================
    import litellm  # noqa: E402  (deliberately imported AFTER instrument())

    model = os.environ.get("LITELLM_MODEL", "anthropic/claude-haiku-4-5")
    # LiteLLM has no persistent client object like openai.OpenAI(...) or
    # anthropic.Anthropic(...) -- api_key/api_base are passed per call
    # instead. Unset in every customer-facing .env.example; only CI sets
    # this, to point LiteLLM at a stubbed /v1/messages server.
    api_base = os.environ.get("LITELLM_API_BASE") or None
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    # =================================================================
    # STEP 4 -- Run the scenario: support-ticket triage, three calls.
    # temperature=0 and a tight max_tokens on every call --
    # this is a demo, not a benchmark; a full run costs well under $0.01
    # against the real Anthropic API.
    #
    # All three calls run inside one manually-created parent span. Without
    # it, they'd land as three unrelated root traces, not a waterfall:
    # litellm's auto-instrumentation opens and closes each "litellm_request"
    # span entirely inside its own completion() call (verified against
    # harness_sdk's litellm instrumentor -- the _LiteLLMSpanRun context
    # manager that owns span activation and span.end() is entered and
    # exited entirely inside the wrapped completion() call, nothing
    # survives past its return), so there's no span still current either
    # between calls or after the last one returns for these three to
    # attach to. The wrapper span below is also what makes STEP 5's
    # set_span_attribute call work -- see the note there.
    # =================================================================
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("support_ticket_triage"):
        print(f"\n--- Ticket ---\n{SUPPORT_TICKET}\n", flush=True)

        # Call 1: classify severity via a forced tool call. tool_choice below
        # is OpenAI's nested shape -- LiteLLM translates it into Anthropic's
        # {"type": "tool", "name": ...} on the wire.
        classify_response = litellm.completion(
            model=model,
            api_base=api_base,
            api_key=api_key,
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
        # LiteLLM returns an OpenAI-shaped ModelResponse for every provider --
        # tool_calls[].function.arguments is a JSON string here, same as
        # openai/main.py, unlike anthropic/main.py's already-parsed dict on a
        # content block.
        tool_call = classify_response.choices[0].message.tool_calls[0]
        severity = json.loads(tool_call.function.arguments)["severity"]
        print(f"Severity: {severity}", flush=True)

        # Call 2: summarize the ticket, a short completion.
        summarize_response = litellm.completion(
            model=model,
            api_base=api_base,
            api_key=api_key,
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
        reply_response = litellm.completion(
            model=model,
            api_base=api_base,
            api_key=api_key,
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
        # opened above, not one of the three auto-created
        # "litellm_request" spans -- each of those has already ended by
        # the time its own completion() call returns, so nothing set
        # after any of them would land anywhere (set_span_attribute
        # silently no-ops with no recording span current; see
        # harness_sdk's own docs on it). Staying inside this `with` block
        # is what makes this call actually take effect.
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
