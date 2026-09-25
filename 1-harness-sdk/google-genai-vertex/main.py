"""Harness SDK + Google Gen AI (Vertex AI) tracing demo: support-ticket triage.

Diffed against `1-harness-sdk/anthropic/main.py`: same STEP 1-6 structure,
same three-call scenario -- adapted for the `google-genai` SDK's Vertex AI
backend (`genai.Client(vertexai=True, ...)`), not the Gemini Developer API
backend (`genai.Client(api_key=...)`). See README.md "Which setup this
matches" for why this app picks Vertex over the API-key mode, and
"Prerequisites" for the Application Default Credentials (ADC) setup that
replaces an API key here.

Anthropic's SDK is the closer structural match than OpenAI/LiteLLM: like
Anthropic, `google-genai` takes a top-level `system_instruction` config
param (not a "system" message) and returns an already-parsed dict for a
function call's arguments (no `json.loads()` step, unlike OpenAI/LiteLLM's
JSON-string `tool_calls[].function.arguments`).

Run:
    cp .env.example .env    # edit GOOGLE_CLOUD_PROJECT, and
                             # HARNESS_ACCOUNT_ID / HARNESS_REPORTING_TOKEN only if
                             # you're switching TRACE_TARGET to "harness"
    uv sync

    # In a separate terminal, leave this running (or set up real ADC
    # instead and skip it):
    uv run ../../mock-providers/mock_google_genai_server.py

    # Back in this terminal:
    uv run main.py

Unlike every other app in `1-harness-sdk/`, there's no provider API key in
`.env` at all -- Vertex AI authenticates via Application Default
Credentials, not a key. There's also no local-Ollama-style zero-cost path
for Vertex AI, so .env.example ships pointed at mock-providers/'s stub
server by default, which main.py's STEP 3 uses to skip ADC entirely -- no
`gcloud auth application-default login` needed to see a trace. See
README.md "Prerequisites".
"""
import os

from dotenv import load_dotenv
from opentelemetry import trace

# =====================================================================
# STEP 1 -- Configure via environment, before any other import.
#
# Every var this script or the SDK reads (TRACE_TARGET, HARNESS_*,
# GOOGLE_CLOUD_*, INGEST_BASE, LOCAL_OTLP_ENDPOINT) must be set before
# harness_sdk or google.genai are imported below -- the SDK reads its
# HARNESS_* config at instrument() time, not lazily.
# =====================================================================
load_dotenv()  # populates os.environ from .env; no-op if .env is absent

TRACE_TARGET = os.environ.get("TRACE_TARGET", "local")

os.environ["HARNESS_SERVICE_NAME"] = "cacm-demo-google-genai-vertex"

# Instrumentation is opt-in per provider -- nothing is patched unless this
# is set, even after instrument() is called. This flag covers both
# google-genai backends (Gemini Developer API and Vertex AI); this app
# only exercises the Vertex AI one.
os.environ["HARNESS_ENABLE_AI_GOOGLE_GENAI"] = "true"

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
# openai/, anthropic/, and litellm/, so all four apps' traces are
# directly comparable.
# =====================================================================
SUPPORT_TICKET = (
    "Subject: Checkout is broken for all EU customers\n\n"
    "Since this morning's deploy, every customer in the EU region gets a "
    "500 error at the final payment step. US customers are unaffected. "
    "This is blocking all EU revenue and support is getting flooded with "
    "tickets."
)


def run():
    # =================================================================
    # STEP 2 -- Instrument BEFORE importing the provider client.
    #
    # agent.instrument() monkey-patches google.genai.models.Models (and
    # its async counterpart) at import time. If `from google import genai`
    # runs before this call, the patch has nothing left to attach to and
    # every span is silently dropped -- no error, no warning.
    # =================================================================
    agent = Agent()
    agent.instrument()

    # =================================================================
    # STEP 3 -- Import the provider client and build it, only after
    # instrument() (see STEP 2). Kept inside this function body, not at
    # module level, so the ordering can't be accidentally broken by a
    # future edit that hoists imports to the top of the file.
    # =================================================================
    from google import genai  # noqa: E402  (deliberately imported AFTER instrument())
    from google.genai import types  # noqa: E402

    model = os.environ.get("GOOGLE_GENAI_MODEL", "gemini-2.0-flash")

    # google-genai's Vertex AI backend has no api_base/api_key-style local
    # override, so this app can't point at a stub the way openai/'s
    # OPENAI_BASE_URL or anthropic/'s ANTHROPIC_BASE_URL do. Instead, when
    # GOOGLE_GENAI_BASE_URL is set (the .env.example default), this app
    # builds the client with http_options.base_url_resource_scope=
    # "COLLECTION" and *no* project/location. That combination (verified
    # against the google-genai>=1.55.0 source) makes the client skip
    # Application Default Credentials entirely -- both at Client()
    # construction and at request time -- and send an unauthenticated
    # request straight to GOOGLE_GENAI_BASE_URL with a bare
    # "{model}:generateContent" path, no
    # "projects/{project}/locations/{location}/" prefix. See
    # mock-providers/mock_google_genai_server.py and mock-providers/README.md.
    mock_base_url = os.environ.get("GOOGLE_GENAI_BASE_URL")
    if mock_base_url:
        client = genai.Client(
            vertexai=True,
            http_options=types.HttpOptions(
                base_url=mock_base_url,
                base_url_resource_scope="COLLECTION",
            ),
        )
    else:
        # Real Vertex AI usage: no API key anywhere. Auth comes from
        # Application Default Credentials -- see README.md
        # "Prerequisites" for the one-time `gcloud auth
        # application-default login` (or GOOGLE_APPLICATION_CREDENTIALS
        # service-account key) this requires.
        client = genai.Client(
            vertexai=True,
            project=os.environ["GOOGLE_CLOUD_PROJECT"],
            location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
        )

    # google-genai expresses a declared tool as a FunctionDeclaration
    # inside a Tool, not a bare dict like OpenAI/LiteLLM's {"type":
    # "function", "function": {...}} or Anthropic's flat {"name": ...,
    # "input_schema": ...} -- but the inner JSON-schema-shaped
    # "parameters" dict below is unchanged from Anthropic's
    # "input_schema" dict in anthropic/main.py.
    classify_tool = types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="classify_severity",
                description="Classify the severity of a support ticket.",
                parameters={
                    "type": "object",
                    "properties": {
                        "severity": {
                            "type": "string",
                            "enum": ["low", "medium", "high", "critical"],
                        },
                    },
                    "required": ["severity"],
                },
            )
        ]
    )

    # =================================================================
    # STEP 4 -- Run the scenario: support-ticket triage, three calls.
    # temperature=0 and a tight max_output_tokens on every call --
    # this is a demo, not a benchmark; a full run costs well under $0.01
    # against the real Vertex AI API.
    #
    # All three calls run inside one manually-created parent span. Without
    # it, they'd land as three unrelated root traces, not a waterfall:
    # google-genai's auto-instrumentation opens and closes each "chat" span
    # entirely inside its own generate_content() call (verified against
    # harness_sdk's google_genai instrumentor -- handler.start_llm/stop_llm
    # both run inside the wrapped call, nothing survives past its return),
    # so there's no span still current either between calls or after the
    # last one returns for these three to attach to. The wrapper span
    # below is also what makes STEP 5's set_span_attribute call work --
    # see the note there.
    # =================================================================
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("support_ticket_triage"):
        print(f"\n--- Ticket ---\n{SUPPORT_TICKET}\n", flush=True)

        # Call 1: classify severity via a forced function call. mode="ANY" +
        # allowed_function_names is google-genai's way of forcing exactly one
        # tool, equivalent to Anthropic's tool_choice={"type": "tool", "name":
        # ...} and OpenAI/LiteLLM's tool_choice={"type": "function",
        # "function": {"name": ...}}.
        classify_response = client.models.generate_content(
            model=model,
            contents=SUPPORT_TICKET,
            config=types.GenerateContentConfig(
                system_instruction="Classify the ticket's severity by calling classify_severity.",
                temperature=0,
                max_output_tokens=50,
                tools=[classify_tool],
                tool_config=types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(
                        mode="ANY",
                        allowed_function_names=["classify_severity"],
                    )
                ),
            ),
        )
        # A function-call response part's `.function_call.args` is already a
        # parsed dict here -- like Anthropic's tool_use block's `.input`, and
        # unlike OpenAI/LiteLLM's `tool_calls[].function.arguments`, which is a
        # JSON string requiring json.loads().
        function_call = next(
            part.function_call
            for part in classify_response.candidates[0].content.parts
            if part.function_call is not None
        )
        severity = function_call.args["severity"]
        print(f"Severity: {severity}", flush=True)

        # Call 2: summarize the ticket, a short completion. Like Anthropic's
        # `system`, google-genai's `system_instruction` is a top-level config
        # param, not a message inside `contents`.
        summarize_response = client.models.generate_content(
            model=model,
            contents=SUPPORT_TICKET,
            config=types.GenerateContentConfig(
                system_instruction="Summarize the support ticket in one sentence.",
                temperature=0,
                max_output_tokens=60,
            ),
        )
        # `.text` is a convenience property that concatenates the first
        # candidate's text parts.
        summary = summarize_response.text
        print(f"Summary: {summary}", flush=True)

        # Call 3: draft a customer reply -- multi-turn, uses calls 1+2 as
        # context, so token usage grows across the three spans. Prior turns
        # are threaded through `contents` as a list of `Content` objects, each
        # with a `role` -- but the model's own role is "model" here, not
        # OpenAI/Anthropic's "assistant".
        reply_response = client.models.generate_content(
            model=model,
            contents=[
                types.Content(role="user", parts=[types.Part(text=SUPPORT_TICKET)]),
                types.Content(
                    role="model",
                    parts=[types.Part(text=f"Severity: {severity}. Summary: {summary}")],
                ),
                types.Content(
                    role="user",
                    parts=[types.Part(text="Draft the reply to the customer now.")],
                ),
            ],
            config=types.GenerateContentConfig(
                system_instruction="Draft a brief, empathetic customer-facing reply.",
                temperature=0,
                max_output_tokens=120,
            ),
        )
        draft_reply = reply_response.text
        print(f"\nDraft reply:\n{draft_reply}\n", flush=True)

        # =============================================================
        # STEP 5 -- Enrich the current span with a custom business
        # attribute. "Current" here is the support_ticket_triage span
        # opened above, not one of the three auto-created "chat" spans --
        # each of those has already ended by the time its own
        # generate_content() call returns, so nothing set after any of
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
