"""
Unit tests for app/agent.py

Covers:
  - _extract_and_store_customer  (UUID parsing + session mutation)
  - _invoke                      (customer_id injection, error handling, auth side-effect)
  - _execute_tool_calls          (multi-tool dispatch, bad JSON args)
  - run_agent                    (streaming ReAct loop with mocked OpenAI)

Run from the backend/ directory:
    pip install pytest pytest-asyncio
    pytest tests/test_agent.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent import (
    _execute_tool_calls,
    _extract_and_store_customer,
    _invoke,
    run_agent,
)
from app.mcp_client import (
    CustomerNotFoundError,
    InsufficientInventoryError,
    MCPClient,
    MCPError,
    ProductNotFoundError,
)
from app.session import Session


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def make_session(session_id: str = "test-session") -> Session:
    return Session(session_id=session_id)


def make_authenticated_session(
    session_id: str = "auth-session",
    customer_id: str = "cust-uuid-123",
    name: str = "Jane Doe",
    email: str = "jane@example.com",
) -> Session:
    s = Session(session_id=session_id)
    s.authenticate(customer_id, name, email)
    return s


def make_chunk(
    content: str | None = None,
    tool_calls=None,
    finish_reason: str | None = None,
) -> MagicMock:
    """Create a minimal OpenAI streaming chunk mock."""
    chunk = MagicMock()
    choice = MagicMock()
    chunk.choices = [choice]
    choice.finish_reason = finish_reason
    choice.delta.content = content
    choice.delta.tool_calls = tool_calls
    return chunk


def make_tool_call_fragment(
    index: int,
    tc_id: str | None = None,
    name: str | None = None,
    arguments: str | None = None,
) -> MagicMock:
    """Create a single tool-call delta fragment."""
    tc = MagicMock()
    tc.index = index
    tc.id = tc_id
    tc.function.name = name
    tc.function.arguments = arguments
    return tc


class MockAsyncStream:
    """Async-iterable wrapper around a list of pre-built chunks."""

    def __init__(self, chunks: list):
        self._chunks = chunks

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for chunk in self._chunks:
            yield chunk


# ---------------------------------------------------------------------------
# _extract_and_store_customer
# ---------------------------------------------------------------------------

class TestExtractAndStoreCustomer:
    def test_extracts_uuid_and_name(self):
        session = make_session()
        result_text = (
            "Authentication successful.\n"
            "Customer ID: 12345678-1234-1234-1234-123456789abc\n"
            "Name: Jane Doe\n"
            "Email: jane@example.com"
        )
        _extract_and_store_customer(result_text, {"email": "jane@example.com"}, session)

        assert session.is_authenticated
        assert session.customer_id == "12345678-1234-1234-1234-123456789abc"
        assert session.customer_name == "Jane Doe"
        assert session.customer_email == "jane@example.com"

    def test_extracts_uuid_without_name_uses_fallback(self):
        session = make_session()
        result_text = "Authenticated. ID: aabbccdd-0000-0000-0000-111111111111"
        _extract_and_store_customer(result_text, {"email": "x@x.com"}, session)

        assert session.is_authenticated
        assert session.customer_id == "aabbccdd-0000-0000-0000-111111111111"
        assert session.customer_name == "Customer"

    def test_missing_uuid_does_not_authenticate(self):
        session = make_session()
        _extract_and_store_customer("No UUID in this string at all.", {}, session)

        assert not session.is_authenticated
        assert session.customer_id is None

    def test_resets_failed_pin_attempts_on_successful_auth(self):
        session = make_session()
        session.record_failed_pin()
        session.record_failed_pin()
        assert session.failed_pin_attempts == 2

        result_text = "ID: 12345678-1234-1234-1234-123456789abc\nName: Bob"
        _extract_and_store_customer(result_text, {"email": "bob@example.com"}, session)

        assert session.failed_pin_attempts == 0

    def test_uuid_is_case_insensitive(self):
        session = make_session()
        result_text = "ID: AABBCCDD-1111-2222-3333-FFFFFFFFFFFF"
        _extract_and_store_customer(result_text, {}, session)

        assert session.is_authenticated
        assert session.customer_id.lower() == "aabbccdd-1111-2222-3333-ffffffffffff"


# ---------------------------------------------------------------------------
# _invoke
# ---------------------------------------------------------------------------

class TestInvoke:
    @pytest.mark.asyncio
    async def test_injects_customer_id_for_list_orders(self):
        session = make_authenticated_session(customer_id="cust-99")
        mcp = AsyncMock(spec=MCPClient)
        mcp.call_tool = AsyncMock(return_value="order list")

        await _invoke("list_orders", {}, session, mcp)

        mcp.call_tool.assert_called_once_with("list_orders", {"customer_id": "cust-99"})

    @pytest.mark.asyncio
    async def test_injects_customer_id_for_create_order(self):
        session = make_authenticated_session(customer_id="cust-99")
        mcp = AsyncMock(spec=MCPClient)
        mcp.call_tool = AsyncMock(return_value="order created")

        await _invoke("create_order", {"items": []}, session, mcp)

        mcp.call_tool.assert_called_once_with(
            "create_order", {"items": [], "customer_id": "cust-99"}
        )

    @pytest.mark.asyncio
    async def test_does_not_inject_customer_id_when_unauthenticated(self):
        session = make_session()
        mcp = AsyncMock(spec=MCPClient)
        mcp.call_tool = AsyncMock(return_value="no orders")

        await _invoke("list_orders", {}, session, mcp)

        mcp.call_tool.assert_called_once_with("list_orders", {})

    @pytest.mark.asyncio
    async def test_does_not_overwrite_explicit_customer_id(self):
        """setdefault must not clobber a value already present in arguments."""
        session = make_authenticated_session(customer_id="session-cust")
        mcp = AsyncMock(spec=MCPClient)
        mcp.call_tool = AsyncMock(return_value="ok")

        await _invoke("list_orders", {"customer_id": "explicit-cust"}, session, mcp)

        mcp.call_tool.assert_called_once_with("list_orders", {"customer_id": "explicit-cust"})

    @pytest.mark.asyncio
    async def test_customer_not_found_records_failed_attempt_and_returns_message(self):
        session = make_session()
        mcp = AsyncMock(spec=MCPClient)
        mcp.call_tool = AsyncMock(side_effect=CustomerNotFoundError("bad pin"))

        result = await _invoke(
            "verify_customer_pin", {"email": "x@x.com", "pin": "0000"}, session, mcp
        )

        assert session.failed_pin_attempts == 1
        assert "Authentication failed" in result
        assert "attempt 1" in result

    @pytest.mark.asyncio
    async def test_multiple_failed_pins_increment_counter(self):
        session = make_session()
        mcp = AsyncMock(spec=MCPClient)
        mcp.call_tool = AsyncMock(side_effect=CustomerNotFoundError("bad pin"))

        await _invoke("verify_customer_pin", {}, session, mcp)
        await _invoke("verify_customer_pin", {}, session, mcp)

        assert session.failed_pin_attempts == 2

    @pytest.mark.asyncio
    async def test_product_not_found_returns_message(self):
        session = make_session()
        mcp = AsyncMock(spec=MCPClient)
        mcp.call_tool = AsyncMock(side_effect=ProductNotFoundError("SKU-X not found"))

        result = await _invoke("get_product", {"sku": "SKU-X"}, session, mcp)

        assert "Product not found" in result
        assert "SKU-X not found" in result

    @pytest.mark.asyncio
    async def test_insufficient_inventory_returns_message(self):
        session = make_session()
        mcp = AsyncMock(spec=MCPClient)
        mcp.call_tool = AsyncMock(side_effect=InsufficientInventoryError("only 2 left"))

        result = await _invoke("create_order", {}, session, mcp)

        assert "Insufficient inventory" in result
        assert "only 2 left" in result

    @pytest.mark.asyncio
    async def test_generic_mcp_error_returns_service_error_message(self):
        session = make_session()
        mcp = AsyncMock(spec=MCPClient)
        mcp.call_tool = AsyncMock(side_effect=MCPError("timeout"))

        result = await _invoke("list_products", {}, session, mcp)

        assert "Service error" in result
        assert "timeout" in result

    @pytest.mark.asyncio
    async def test_verify_pin_success_authenticates_session(self):
        session = make_session()
        mcp = AsyncMock(spec=MCPClient)
        mcp.call_tool = AsyncMock(
            return_value=(
                "Authentication successful. "
                "ID: aabbccdd-1111-1111-1111-aabbccddeeff\n"
                "Name: Alice Smith"
            )
        )

        await _invoke(
            "verify_customer_pin",
            {"email": "alice@example.com", "pin": "1234"},
            session,
            mcp,
        )

        assert session.is_authenticated
        assert session.customer_id == "aabbccdd-1111-1111-1111-aabbccddeeff"
        assert session.customer_name == "Alice Smith"
        assert session.customer_email == "alice@example.com"


# ---------------------------------------------------------------------------
# _execute_tool_calls
# ---------------------------------------------------------------------------

class TestExecuteToolCalls:
    @pytest.mark.asyncio
    async def test_single_tool_call_returns_result_message(self):
        session = make_session()
        mcp = AsyncMock(spec=MCPClient)
        mcp.call_tool = AsyncMock(return_value="some products")

        tool_calls = [
            {
                "id": "call_abc",
                "type": "function",
                "function": {"name": "list_products", "arguments": "{}"},
            }
        ]

        results = await _execute_tool_calls(tool_calls, session, mcp)

        assert len(results) == 1
        assert results[0]["role"] == "tool"
        assert results[0]["tool_call_id"] == "call_abc"
        assert results[0]["content"] == "some products"

    @pytest.mark.asyncio
    async def test_invalid_json_arguments_fall_back_to_empty_dict(self):
        session = make_session()
        mcp = AsyncMock(spec=MCPClient)
        mcp.call_tool = AsyncMock(return_value="ok")

        tool_calls = [
            {
                "id": "call_bad",
                "type": "function",
                "function": {"name": "list_products", "arguments": "not-valid-json"},
            }
        ]

        results = await _execute_tool_calls(tool_calls, session, mcp)

        mcp.call_tool.assert_called_once_with("list_products", {})
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_empty_arguments_string_falls_back_to_empty_dict(self):
        session = make_session()
        mcp = AsyncMock(spec=MCPClient)
        mcp.call_tool = AsyncMock(return_value="ok")

        tool_calls = [
            {"id": "tc1", "type": "function", "function": {"name": "list_products", "arguments": ""}},
        ]

        await _execute_tool_calls(tool_calls, session, mcp)

        mcp.call_tool.assert_called_once_with("list_products", {})

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_are_all_executed(self):
        session = make_session()
        mcp = AsyncMock(spec=MCPClient)
        mcp.call_tool = AsyncMock(side_effect=["result-1", "result-2"])

        tool_calls = [
            {"id": "tc1", "type": "function", "function": {"name": "list_products", "arguments": "{}"}},
            {"id": "tc2", "type": "function", "function": {"name": "search_products", "arguments": '{"query":"laptop"}'}},
        ]

        results = await _execute_tool_calls(tool_calls, session, mcp)

        assert len(results) == 2
        assert results[0]["content"] == "result-1"
        assert results[0]["tool_call_id"] == "tc1"
        assert results[1]["content"] == "result-2"
        assert results[1]["tool_call_id"] == "tc2"

    @pytest.mark.asyncio
    async def test_tool_error_is_captured_in_result_content(self):
        """Errors from _invoke are returned as result text, not raised."""
        session = make_session()
        mcp = AsyncMock(spec=MCPClient)
        mcp.call_tool = AsyncMock(side_effect=MCPError("server down"))

        tool_calls = [
            {"id": "tc1", "type": "function", "function": {"name": "list_products", "arguments": "{}"}},
        ]

        results = await _execute_tool_calls(tool_calls, session, mcp)

        assert len(results) == 1
        assert "Service error" in results[0]["content"]


# ---------------------------------------------------------------------------
# run_agent — full streaming loop with mocked OpenAI
# ---------------------------------------------------------------------------

class TestRunAgent:
    @pytest.mark.asyncio
    async def test_simple_text_response_yields_chunks(self):
        """Model replies with plain text and no tool calls."""
        session = make_session()
        mcp = AsyncMock(spec=MCPClient)

        chunks = [
            make_chunk(content="Hello"),
            make_chunk(content=" there!"),
            make_chunk(finish_reason="stop"),
        ]
        mock_create = AsyncMock(return_value=MockAsyncStream(chunks))

        with patch("app.agent.AsyncOpenAI") as mock_openai_cls:
            mock_openai_cls.return_value.chat.completions.create = mock_create

            output = [token async for token in run_agent(session, "Hi", mcp, "fake-key")]

        assert output == ["Hello", " there!"]

    @pytest.mark.asyncio
    async def test_user_message_appended_to_history(self):
        session = make_session()
        mcp = AsyncMock(spec=MCPClient)

        chunks = [make_chunk(content="OK", finish_reason="stop")]
        mock_create = AsyncMock(return_value=MockAsyncStream(chunks))

        with patch("app.agent.AsyncOpenAI") as mock_openai_cls:
            mock_openai_cls.return_value.chat.completions.create = mock_create
            async for _ in run_agent(session, "Test message", mcp, "fake-key"):
                pass

        assert session.history[0] == {"role": "user", "content": "Test message"}

    @pytest.mark.asyncio
    async def test_assistant_text_stored_in_history(self):
        session = make_session()
        mcp = AsyncMock(spec=MCPClient)

        chunks = [
            make_chunk(content="Hello"),
            make_chunk(content=" world"),
            make_chunk(finish_reason="stop"),
        ]
        mock_create = AsyncMock(return_value=MockAsyncStream(chunks))

        with patch("app.agent.AsyncOpenAI") as mock_openai_cls:
            mock_openai_cls.return_value.chat.completions.create = mock_create
            async for _ in run_agent(session, "Hi", mcp, "fake-key"):
                pass

        assistant_msg = session.history[1]
        assert assistant_msg["role"] == "assistant"
        assert assistant_msg["content"] == "Hello world"

    @pytest.mark.asyncio
    async def test_tool_call_then_final_text_response(self):
        """Model requests a tool, receives results, then replies with text."""
        session = make_session()
        mcp = AsyncMock(spec=MCPClient)
        mcp.call_tool = AsyncMock(return_value="Laptop Pro: $999")

        frag = make_tool_call_fragment(
            0, tc_id="call_1", name="search_products", arguments='{"query":"laptop"}'
        )
        turn1 = [
            make_chunk(tool_calls=[frag]),
            make_chunk(finish_reason="tool_calls"),
        ]
        turn2 = [
            make_chunk(content="Found a Laptop Pro for $999."),
            make_chunk(finish_reason="stop"),
        ]

        call_count = 0

        async def mock_create(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return MockAsyncStream(turn1 if call_count == 1 else turn2)

        with patch("app.agent.AsyncOpenAI") as mock_openai_cls:
            mock_openai_cls.return_value.chat.completions.create = mock_create

            output = [token async for token in run_agent(session, "Find me a laptop", mcp, "fake-key")]

        assert output == ["Found a Laptop Pro for $999."]
        assert call_count == 2

        # History: user → assistant(tool_calls) → tool result → assistant(text)
        assert session.history[0]["role"] == "user"
        assert "tool_calls" in session.history[1]
        assert session.history[2]["role"] == "tool"
        assert session.history[2]["content"] == "Laptop Pro: $999"
        assert session.history[3]["role"] == "assistant"
        assert session.history[3]["content"] == "Found a Laptop Pro for $999."

    @pytest.mark.asyncio
    async def test_chunk_with_no_choices_is_skipped(self):
        """Chunks with an empty choices list must not raise."""
        session = make_session()
        mcp = AsyncMock(spec=MCPClient)

        empty_chunk = MagicMock()
        empty_chunk.choices = []

        chunks = [empty_chunk, make_chunk(content="Hi", finish_reason="stop")]
        mock_create = AsyncMock(return_value=MockAsyncStream(chunks))

        with patch("app.agent.AsyncOpenAI") as mock_openai_cls:
            mock_openai_cls.return_value.chat.completions.create = mock_create

            output = [token async for token in run_agent(session, "Hello", mcp, "fake-key")]

        assert output == ["Hi"]

    @pytest.mark.asyncio
    async def test_empty_stream_produces_no_output_and_breaks(self):
        """An empty stream should not hang; the loop exits gracefully."""
        session = make_session()
        mcp = AsyncMock(spec=MCPClient)

        mock_create = AsyncMock(return_value=MockAsyncStream([]))

        with patch("app.agent.AsyncOpenAI") as mock_openai_cls:
            mock_openai_cls.return_value.chat.completions.create = mock_create

            output = [token async for token in run_agent(session, "Hello", mcp, "fake-key")]

        assert output == []

    @pytest.mark.asyncio
    async def test_openai_client_initialised_with_provided_api_key(self):
        session = make_session()
        mcp = AsyncMock(spec=MCPClient)

        chunks = [make_chunk(content="OK", finish_reason="stop")]
        mock_create = AsyncMock(return_value=MockAsyncStream(chunks))

        with patch("app.agent.AsyncOpenAI") as mock_openai_cls:
            mock_openai_cls.return_value.chat.completions.create = mock_create
            async for _ in run_agent(session, "Hi", mcp, "sk-test-key"):
                pass

        mock_openai_cls.assert_called_once_with(api_key="sk-test-key")
