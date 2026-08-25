import os
import uuid
from google.adk.agents import Agent
from google.adk.tools import ToolContext
from google.cloud import geminidataanalytics_v1 as geminidataanalytics
from google.protobuf.json_format import MessageToDict

# --- Configuration ---
# Loaded from .env (GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION,
# GOOGLE_GENAI_USE_VERTEXAI) automatically by ADK's dotenv support.
PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "keen-berm-506210-a8")

# This points to the location of the BigQuery Conversational Analytics
# Data Agent, NOT the Vertex AI LLM location. These are independent settings.
DATA_AGENT_LOCATION = "global"
DATA_AGENT_ID = "ecom_orders_analytics_agent"

# Key used to stash the conversation resource name in ADK session state,
# so the same Data Agent conversation is reused across turns in one session.
CONVERSATION_STATE_KEY = "data_agent_conversation_name"


def _get_or_create_conversation(
    client: geminidataanalytics.DataChatServiceClient,
    parent: str,
    agent_path: str,
    tool_context: ToolContext,
) -> str:
    """Returns the resource name of a Data Agent conversation, creating one
    on first use and reusing it for the rest of the ADK session (stateful
    mode: Google manages the turn history server-side)."""

    existing_name = tool_context.state.get(CONVERSATION_STATE_KEY)
    if existing_name:
        return existing_name

    # Conversation IDs must match ^[a-z]([a-z0-9-]{0,61}[a-z0-9])?$
    conversation_id = f"conv-{uuid.uuid4().hex[:20]}"

    conversation = geminidataanalytics.Conversation(agents=[agent_path])
    create_request = geminidataanalytics.CreateConversationRequest(
        parent=parent,
        conversation_id=conversation_id,
        conversation=conversation,
    )

    created = client.create_conversation(request=create_request)
    tool_context.state[CONVERSATION_STATE_KEY] = created.name
    return created.name


def _extract_text_from_chunk(chunk) -> list[str]:
    """Pulls readable text out of one ChatResponse chunk.

    The API returns a `system_message` with several MUTUALLY EXCLUSIVE
    sub-fields (text, schema, data, chart, analysis, error) — a plain
    narrative "text" message is NOT guaranteed for every query. Simple
    aggregate questions (e.g. "total orders in June") often come back as a
    structured `data` result (a query result table) instead, which is why
    the original text-only parsing silently returned nothing.

    We convert each chunk to a plain dict (Google's own recommended
    approach for this SDK) rather than touching proto attributes directly,
    since exact field availability can vary by chunk type.
    """
    texts = []
    try:
        chunk_dict = MessageToDict(chunk._pb, preserving_proto_field_name=True)
    except Exception:
        return texts

    system_message = chunk_dict.get("system_message") or chunk_dict.get("systemMessage")
    if not system_message:
        return texts

    # Narrative text response (skip internal "THOUGHT" reasoning chunks,
    # keep the final answer text)
    text_msg = system_message.get("text")
    if text_msg:
        parts = text_msg.get("parts", [])
        text_type = str(text_msg.get("text_type") or text_msg.get("textType") or "")
        if parts and "THOUGHT" not in text_type.upper():
            texts.append(" ".join(parts))

    # Structured query result (e.g. an aggregate like "total orders")
    data_msg = system_message.get("data")
    if data_msg:
        result = data_msg.get("result", {})
        rows = result.get("data", [])
        if rows:
            formatted_rows = []
            for row in rows:
                if isinstance(row, dict):
                    formatted_rows.append(", ".join(f"{k}: {v}" for k, v in row.items()))
                else:
                    formatted_rows.append(str(row))
            texts.append("Query result:\n" + "\n".join(formatted_rows))

    # Surface any explicit error the Data Agent reports mid-stream
    error_msg = system_message.get("error")
    if error_msg:
        err_text = error_msg.get("text") or str(error_msg)
        texts.append(f"[Data Agent error: {err_text}]")

    return texts


def query_conversational_analytics(query: str, tool_context: ToolContext) -> str:
    """Queries the BigQuery Conversational Analytics Data Agent with natural language questions about e-commerce orders, revenue, and customer metrics. Maintains conversation history across turns within the same session."""

    # client_options ensures the quota project is explicit for this client too,
    # avoiding the same ADC "quota project not set" 403 we hit via REST.
    client = geminidataanalytics.DataChatServiceClient(
        client_options={"quota_project_id": PROJECT_ID}
    )
    parent = f"projects/{PROJECT_ID}/locations/{DATA_AGENT_LOCATION}"
    agent_path = f"{parent}/dataAgents/{DATA_AGENT_ID}"

    try:
        conversation_name = _get_or_create_conversation(
            client, parent, agent_path, tool_context
        )
    except Exception as e:
        print(f"\n[API ERROR EXPOSED] Conversation creation failed: {e}\n")
        return f"CRITICAL ERROR: {str(e)}. Do NOT retry or rephrase. Output this exact error message to the user immediately."

    # 1. Format the user's question into an API-ready Message object.
    # In stateful mode we only send the new message each turn — Google
    # manages prior turns server-side via the conversation resource.
    messages = [
        geminidataanalytics.Message(
            user_message=geminidataanalytics.UserMessage(text=query)
        )
    ]

    # 2. Reference the existing conversation AND the Data Agent together —
    # both are required for stateful mode.
    conversation_reference = geminidataanalytics.ConversationReference(
        conversation=conversation_name,
        data_agent_context=geminidataanalytics.DataAgentContext(
            data_agent=agent_path
        ),
    )

    # 3. Prepare the chat request
    request = geminidataanalytics.ChatRequest(
        parent=parent,
        messages=messages,
        conversation_reference=conversation_reference,
    )

    # 4. Process the streaming response with fail-fast error handling
    try:
        stream = client.chat(request=request)

        full_response = []
        for chunk in stream:
            full_response.extend(_extract_text_from_chunk(chunk))

        return "\n\n".join(full_response) if full_response else "No text answer returned from the Data Agent."

    except Exception as e:
        # Print exactly why it failed to the VS Code terminal for rapid debugging
        print(f"\n[API ERROR EXPOSED] DataChatServiceClient failed: {e}\n")
        # Force the agent to stop trying and report the exact error
        return f"CRITICAL ERROR: {str(e)}. Do NOT retry or rephrase. Output this exact error message to the user immediately."


root_agent = Agent(
    name="ecom_orders_agent",
    # NOTE: No "-001" suffix — that versioning convention doesn't apply to
    # current Gemini stable model IDs. This model must exist in whatever
    # region GOOGLE_CLOUD_LOCATION resolves to (set in .env to us-central1).
    # Using gemini-2.5-flash for now; swap to gemini-3.6-flash once that
    # model is enabled for this project in Vertex AI Model Garden.
    model="gemini-2.5-flash",
    description="E-Commerce Analytics Assistant powered by BigQuery Conversational Analytics API.",
    instruction="""
    You are an expert E-Commerce Data Analytics Assistant.
    For any questions regarding e-commerce metrics, sales, orders, revenue, or customer demographics:
    - Always call the `query_conversational_analytics` tool to fetch accurate, grounded data from BigQuery.
    - Provide a clear, well-structured explanation of the results returned by the tool.
    - IMPORTANT: If the tool returns a CRITICAL ERROR, you must NOT retry, rephrase, or attempt the tool call again. You must immediately output the exact error message to the user without filtering.
    """,
    tools=[query_conversational_analytics],
)