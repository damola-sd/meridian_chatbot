import httpx
import itertools
import logging

logger = logging.getLogger(__name__)

MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}

_id_counter = itertools.count(1)


# ---------------------------------------------------------------------------
# Domain exceptions — caught by the agent and phrased gracefully for users
# ---------------------------------------------------------------------------

class MCPError(Exception):
    """Base class for all MCP errors."""


class ProductNotFoundError(MCPError):
    pass


class CustomerNotFoundError(MCPError):
    pass


class InsufficientInventoryError(MCPError):
    pass


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class MCPClient:
    """
    Thin JSON-RPC 2.0 wrapper around the Meridian MCP server.

    Lifecycle:
        client = MCPClient(url)
        await client.start()   # call once at app startup
        ...
        await client.stop()    # call once at app shutdown
    """

    def __init__(self, base_url: str) -> None:
        self._url = base_url.rstrip("/")
        self._http: httpx.AsyncClient | None = None

    async def start(self) -> None:
        self._http = httpx.AsyncClient(timeout=30.0)
        await self._initialize()
        logger.info("MCPClient connected to %s", self._url)

    async def stop(self) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None
        logger.info("MCPClient disconnected")

    # ------------------------------------------------------------------
    # Tool calls — one public method per MCP tool for type safety
    # The generic call_tool() is also exposed for the agent loop.
    # ------------------------------------------------------------------

    async def call_tool(self, name: str, arguments: dict) -> str:
        """Call any MCP tool by name and return the text result."""
        return await self._call(name, arguments)

    async def list_products(
        self,
        category: str | None = None,
        is_active: bool | None = None,
    ) -> str:
        args: dict = {}
        if category is not None:
            args["category"] = category
        if is_active is not None:
            args["is_active"] = is_active
        return await self._call("list_products", args)

    async def get_product(self, sku: str) -> str:
        return await self._call("get_product", {"sku": sku})

    async def search_products(self, query: str) -> str:
        return await self._call("search_products", {"query": query})

    async def get_customer(self, customer_id: str) -> str:
        return await self._call("get_customer", {"customer_id": customer_id})

    async def verify_customer_pin(self, email: str, pin: str) -> str:
        return await self._call("verify_customer_pin", {"email": email, "pin": pin})

    async def list_orders(
        self,
        customer_id: str | None = None,
        status: str | None = None,
    ) -> str:
        args: dict = {}
        if customer_id is not None:
            args["customer_id"] = customer_id
        if status is not None:
            args["status"] = status
        return await self._call("list_orders", args)

    async def get_order(self, order_id: str) -> str:
        return await self._call("get_order", {"order_id": order_id})

    async def create_order(self, customer_id: str, items: list[dict]) -> str:
        return await self._call(
            "create_order",
            {"customer_id": customer_id, "items": items},
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _initialize(self) -> None:
        """Send the MCP initialize handshake."""
        payload = {
            "jsonrpc": "2.0",
            "id": next(_id_counter),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "meridian-chatbot", "version": "1.0.0"},
            },
        }
        response = await self._http.post(self._url, headers=MCP_HEADERS, json=payload)
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            raise MCPError(f"MCP initialization failed: {data['error']}")

    async def _call(self, tool_name: str, arguments: dict) -> str:
        """
        Execute a tools/call request and return the plain-text result.

        Raises typed domain exceptions when the server signals a known
        error so the agent can respond gracefully rather than crashing.
        """
        assert self._http is not None, "MCPClient.start() has not been called"

        payload = {
            "jsonrpc": "2.0",
            "id": next(_id_counter),
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }

        response = await self._http.post(self._url, headers=MCP_HEADERS, json=payload)
        response.raise_for_status()
        data = response.json()

        # JSON-RPC protocol-level error
        if "error" in data:
            raise MCPError(f"MCP protocol error: {data['error'].get('message', data['error'])}")

        result = data.get("result", {})

        # Application-level error returned inside result
        if result.get("isError"):
            error_text: str = result.get("content", [{}])[0].get("text", "Unknown error")
            raise _classify_error(tool_name, error_text)

        # Success — extract plain text
        content = result.get("content", [])
        if not content:
            return ""
        return content[0].get("text", "")


def _classify_error(tool_name: str, message: str) -> MCPError:
    """Map MCP error text to a typed Python exception."""
    lower = message.lower()
    if "not found" in lower or "no customer" in lower or "invalid" in lower and "pin" in lower:
        if tool_name in ("get_customer", "verify_customer_pin"):
            return CustomerNotFoundError(message)
        return ProductNotFoundError(message)
    if "insufficient" in lower or "inventory" in lower or "stock" in lower:
        return InsufficientInventoryError(message)
    return MCPError(message)
