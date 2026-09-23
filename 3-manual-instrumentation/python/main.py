"""Manual OpenTelemetry instrumentation demo: support-ticket triage.

No harness-sdk, no auto-instrumentor -- this app builds the OTel SDK
pipeline itself and wraps each model call in a hand-rolled span, setting
every gen_ai.* attribute Cloud & AI Cost Management (CACM) needs for cost
attribution by hand instead of getting them for free from a patched
client. See README.md for the required-attribute table and exactly what
breaks in Cost Explorer if any one of them is left off.

Run:
    cp .env.example .env    # edit HARNESS_ACCOUNT_ID / HARNESS_REPORTING_TOKEN only
                             # if you're switching TRACE_TARGET to "harness"
    uv sync
    uv run main.py

TRACE_TARGET=local (the default) needs no Harness account, no Harness
token, and -- with the shipped Ollama defaults -- no OpenAI account either.
"""
import json
import os

from dotenv import load_dotenv
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import SpanKind, Status, StatusCode

# =====================================================================
# STEP 1 -- Configure via environment, before any other import.
#
# There's no vendor SDK here to read config lazily at instrument() time
# -- but TRACE_TARGET still has to be resolved before STEP 2 builds the
# resource/exporter below, so the "config before imports" shape is kept
# for consistency with every other app in this repo.
# =====================================================================
load_dotenv()  # populates os.environ from .env; no-op if .env is absent

TRACE_TARGET = os.environ.get("TRACE_TARGET", "local")
SERVICE_NAME = "cacm-demo-manual-python"

if TRACE_TARGET == "harness":
    account_id = os.environ["HARNESS_ACCOUNT_ID"]
    token = os.environ["HARNESS_REPORTING_TOKEN"]
    ingest_base = os.environ.get("INGEST_BASE", "https://prod3.harness.io/udp-ingest")

    # LLD §9: every app in this repo sends all four of the auth header,
    # the tenant header, the routing query params, and the
    # harness.account.id resource attribute -- all four interpolated
    # from this one HARNESS_ACCOUNT_ID value, so there's one place to
    # get the account ID wrong, not four.
    OTLP_ENDPOINT = (
        f"{ingest_base}/otel/v1/traces"
        f"?accountIdentifier={account_id}&routingId={account_id}"
    )
    OTLP_HEADERS = {"x-harness-service-token": token, "x-tenant-id": account_id}
    # Optional when x-harness-service-token is present (the gateway derives
    # the account from the token) -- but if set, it must match the token's
    # account exactly, or ingestion fails with a hard 403 "tenant mismatch".
    # An ordinary personal/service-account token gets normal tenant-check
    # enforcement on this header -- it's not an admin/cross-account bypass.
    RESOURCE_ATTRS = {"service.name": SERVICE_NAME, "harness.account.id": account_id}
else:
    # local-collector/'s Jaeger. Port 4418, not the OTel default 4318:
    # many machines run a local telemetry agent bound to 127.0.0.1:4318
    # that answers HTTP 200 and silently discards whatever is sent to it.
    local_endpoint = os.environ.get("LOCAL_OTLP_ENDPOINT", "http://localhost:4418")
    OTLP_ENDPOINT = f"{local_endpoint}/v1/traces"
    OTLP_HEADERS = {}
    RESOURCE_ATTRS = {"service.name": SERVICE_NAME}

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

# Required so cost can be attributed to an agent rather than just a raw
# service (README §6) -- this is the one attribute that has no
# equivalent auto-populated by any provider SDK's own usage object.
AGENT_NAME = "support-ticket-triage"


def start_chat_span(tracer, model):
    """Open a span for one model call, pre-populated with the four
    attributes that don't depend on the API response (provider, model,
    agent) -- gen_ai.usage.* gets added once the response comes back.
    Every one of these is load-bearing; see README.md's
    required-attribute table for what silently breaks without each one.
    """
    span = tracer.start_span(f"chat {model}", kind=SpanKind.CLIENT)
    span.set_attribute("gen_ai.provider.name", "openai")
    span.set_attribute("gen_ai.request.model", model)
    span.set_attribute("gen_ai.agent.name", AGENT_NAME)
    return span


def record_usage(span, usage):
    span.set_attribute("gen_ai.usage.input_tokens", usage.prompt_tokens)
    span.set_attribute("gen_ai.usage.output_tokens", usage.completion_tokens)


def run():
    # =================================================================
    # STEP 2 -- "Instrument": build the OTel SDK pipeline by hand.
    #
    # There's no instrumentor to opt into here -- this IS the
    # instrumentation. A TracerProvider wired to a
    # BatchSpanProcessor/OTLPSpanExporter pair is set as the global
    # provider so tracer.start_span() below actually exports anywhere.
    # =================================================================
    resource = Resource.create(RESOURCE_ATTRS)
    exporter = OTLPSpanExporter(endpoint=OTLP_ENDPOINT, headers=OTLP_HEADERS)
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    tracer = trace.get_tracer(__name__)

    # =================================================================
    # STEP 3 -- Import the provider client.
    #
    # The instrument-before-import rule the other families in this repo
    # follow (LLD §12.1) doesn't apply here: nothing monkey-patches the
    # openai client, so import order can't silently drop a span. Kept
    # as its own later step anyway, purely for structural consistency
    # with every other app's main.py.
    # =================================================================
    import openai  # noqa: E402

    client = openai.OpenAI(
        base_url=os.environ.get("OPENAI_BASE_URL") or None,
        api_key=os.environ.get("OPENAI_API_KEY", ""),
    )
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    # =================================================================
    # STEP 4 -- Run the scenario: support-ticket triage, three calls,
    # each wrapped in a hand-rolled span (LLD §11.3). temperature=0 and
    # a tight max_tokens on every call -- this is a demo, not a
    # benchmark; a full run costs well under $0.01 against the real
    # OpenAI API, and nothing at all against Ollama.
    # =================================================================
    print(f"\n--- Ticket ---\n{SUPPORT_TICKET}\n", flush=True)

    # Call 1: classify severity via a forced tool call (structured output).
    span = start_chat_span(tracer, model)
    try:
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
        record_usage(span, classify_response.usage)
        tool_call = classify_response.choices[0].message.tool_calls[0]
        severity = json.loads(tool_call.function.arguments)["severity"]
        span.set_status(Status(StatusCode.OK))
    except Exception as exc:
        span.record_exception(exc)
        span.set_status(Status(StatusCode.ERROR, str(exc)))
        raise
    finally:
        # A hand-rolled span only exports once end() runs -- unlike an
        # auto-instrumentor, nothing closes this for us on our behalf.
        span.end()
    print(f"Severity: {severity}", flush=True)

    # Call 2: summarize the ticket, a short completion.
    span = start_chat_span(tracer, model)
    try:
        summarize_response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Summarize the support ticket in one sentence."},
                {"role": "user", "content": SUPPORT_TICKET},
            ],
            temperature=0,
            max_tokens=60,
        )
        record_usage(span, summarize_response.usage)
        summary = summarize_response.choices[0].message.content
        span.set_status(Status(StatusCode.OK))
    except Exception as exc:
        span.record_exception(exc)
        span.set_status(Status(StatusCode.ERROR, str(exc)))
        raise
    finally:
        span.end()
    print(f"Summary: {summary}", flush=True)

    # Call 3: draft a customer reply -- multi-turn, uses calls 1+2 as
    # context, so token usage grows across the three spans.
    span = start_chat_span(tracer, model)
    try:
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
        record_usage(span, reply_response.usage)
        draft_reply = reply_response.choices[0].message.content

        # =============================================================
        # STEP 5 -- Enrich the span with a custom business attribute.
        # Must happen here, before span.end() in the finally below --
        # once a span has ended, set_attribute() on it is a silent
        # no-op (the SDK logs a warning and drops the call). That's why
        # this sits inside the try block instead of after the call like
        # it might read more naturally.
        # =============================================================
        span.set_attribute("custom.ticket_severity", severity)
        span.set_status(Status(StatusCode.OK))
    except Exception as exc:
        span.record_exception(exc)
        span.set_status(Status(StatusCode.ERROR, str(exc)))
        raise
    finally:
        span.end()
    print(f"\nDraft reply:\n{draft_reply}\n", flush=True)

    # =================================================================
    # STEP 6 -- Flush before exit.
    #
    # The OTLP exporter batches spans (default flush interval: 5s) and
    # nothing here registers an atexit hook to flush on process exit.
    # Without this explicit call, a short-lived script like this one
    # can exit before its spans are ever sent, and they're silently
    # dropped.
    # =================================================================
    print("[OTel] Flushing spans...", flush=True)
    trace.get_tracer_provider().force_flush()


if __name__ == "__main__":
    run()
