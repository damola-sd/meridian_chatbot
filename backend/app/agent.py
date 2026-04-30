import json
import logging
import re
from collections.abc import AsyncGenerator

from openai import AsyncOpenAI

from app.mcp_client import (
    MCPClient,
    MCPError,
    CustomerNotFoundError,
    InsufficientInventoryError,
    ProductNotFoundError,
)
from app.prompts import SYSTEM_PROMPT
from app.session import Session
from app.tools import TOOLS

logger = logging.getLogger(__name__)

# Regex to pull a UUID from a block of text returned by verify_customer_pin
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def run_agent(
    session: Session,
    user_message: str,
    mcp: MCPClient,
    api_key: str,
) -> AsyncGenerator[str, None]:
    """
    Streaming ReAct loop.

    Appends the user message to session history, then drives the
    OpenAI tool-calling loop until the model produces a final text
    response. Text chunks are yielded as they arrive so the caller
    can stream them straight to the client via SSE.

    The loop:
        1. Call GPT-4o-mini with full history + tools (streaming)
        2. Yield text chunks in real time
        3. finish_reason == "tool_calls"  → execute tools, append results, loop
        4. finish_reason == "stop"        → done, break
    """
    client = AsyncOpenAI(api_key=api_key)
    session.add_message({"role": "user", "content": user_message})

    while True:
        accumulated_text = ""
        # tool_calls are streamed in fragments; accumulate by index
        tool_call_fragments: dict[int, dict] = {}
        finish_reason: str | None = None

        stream = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + session.history,
            tools=TOOLS,
            stream=True,
        )

        async for chunk in stream:
            if not chunk.choices:
                continue

            choice = chunk.choices[0]

            if choice.finish_reason:
                finish_reason = choice.finish_reason

            delta = choice.delta

            # --- stream text to caller ---
            if delta.content:
                accumulated_text += delta.content
                yield delta.content

            # --- accumulate tool call fragments ---
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tool_call_fragments:
                        tool_call_fragments[idx] = {
                            "id": "",
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        }
                    frag = tool_call_fragments[idx]
                    if tc_delta.id:
                        frag["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            frag["function"]["name"] += tc_delta.function.name
                        if tc_delta.function.arguments:
                            frag["function"]["arguments"] += tc_delta.function.arguments

        # Build the complete list of tool calls from accumulated fragments
        tool_calls = [tool_call_fragments[i] for i in sorted(tool_call_fragments)]

        # Append assistant message to history (preserving tool_calls if present)
        assistant_msg: dict = {"role": "assistant", "content": accumulated_text or None}
        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls
        session.add_message(assistant_msg)

        # --- terminal state: model is done ---
        if finish_reason == "stop" or not tool_calls:
            break

        # --- tool_calls state: execute every requested tool ---
        if finish_reason == "tool_calls":
            tool_results = await _execute_tool_calls(tool_calls, session, mcp)
            session.add_messages(tool_results)
            # Loop back — model will process results and either call more
            # tools or produce a final text response


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

async def _execute_tool_calls(
    tool_calls: list[dict],
    session: Session,
    mcp: MCPClient,
) -> list[dict]:
    """
    Execute all tool calls from a single assistant turn and return
    a list of tool-result messages in OpenAI format.
    """
    results = []
    for tc in tool_calls:
        name = tc["function"]["name"]
        try:
            raw_args = tc["function"]["arguments"]
            arguments = json.loads(raw_args) if raw_args else {}
        except json.JSONDecodeError:
            arguments = {}

        result_text = await _invoke(name, arguments, session, mcp)

        logger.debug("Tool %s → %s", name, result_text[:120])

        results.append({
            "role": "tool",
            "tool_call_id": tc["id"],
            "content": result_text,
        })

    return results


async def _invoke(
    name: str,
    arguments: dict,
    session: Session,
    mcp: MCPClient,
) -> str:
    """
    Invoke a single MCP tool, handle side-effects, and catch domain errors.
    Returns a plain-text result string for the model to reason over.
    """
    # Inject customer_id from session for tools that require it,
    # so the model never needs to ask the customer for their UUID.
    if name in ("list_orders", "create_order", "get_customer"):
        if session.is_authenticated:
            arguments.setdefault("customer_id", session.customer_id)

    try:
        result = await mcp.call_tool(name, arguments)

        # Side-effect: capture identity after successful authentication
        if name == "verify_customer_pin":
            _extract_and_store_customer(result, arguments, session)

        return result

    except CustomerNotFoundError:
        session.record_failed_pin()
        return (
            "Authentication failed: the email or PIN was not recognised. "
            f"This is attempt {session.failed_pin_attempts}."
        )
    except ProductNotFoundError as e:
        return f"Product not found: {e}"
    except InsufficientInventoryError as e:
        return f"Insufficient inventory: {e}"
    except MCPError as e:
        logger.error("MCP error in tool %s: %s", name, e)
        return f"Service error: {e}. Please try again."


def _extract_and_store_customer(
    result_text: str,
    arguments: dict,
    session: Session,
) -> None:
    """
    Parse the verify_customer_pin response text and store the customer's
    identity in the session so subsequent tools can use it automatically.

    The MCP server returns a plain-text block that contains the UUID.
    We extract it with a regex rather than relying on a fixed format.
    """
    match = _UUID_RE.search(result_text)
    if not match:
        logger.warning("verify_customer_pin succeeded but no UUID found in response")
        return

    customer_id = match.group(0)

    # Try to pull a name from common patterns like "Name: Jane Doe"
    name_match = re.search(r"Name:\s*(.+)", result_text)
    name = name_match.group(1).strip() if name_match else "Customer"

    email = arguments.get("email", "")
    session.authenticate(customer_id, name, email)
    logger.info("Session %s — customer authenticated: %s", session.session_id, name)
