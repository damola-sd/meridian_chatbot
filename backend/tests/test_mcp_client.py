"""
Validation script for Phase 1 — run directly to confirm all 8 MCP tools
respond correctly against the live server.

Usage:
    source .venv/bin/activate
    python -m tests.test_mcp_client
"""

import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.mcp_client import MCPClient, CustomerNotFoundError

MCP_URL = os.getenv("MCP_SERVER_URL", "https://order-mcp-74afyau24q-uc.a.run.app/mcp")

GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"
BOLD = "\033[1m"


def ok(label: str, preview: str = "") -> None:
    snippet = f" → {preview[:80]}..." if preview else ""
    print(f"{GREEN}  PASS{RESET}  {label}{snippet}")


def fail(label: str, error: str) -> None:
    print(f"{RED}  FAIL{RESET}  {label}: {error}")


async def run() -> None:
    client = MCPClient(MCP_URL)
    await client.start()

    print(f"\n{BOLD}Phase 1 — MCP Client validation{RESET}")
    print(f"Server: {MCP_URL}\n")

    passed = 0
    failed = 0

    # 1. list_products (no filter)
    try:
        result = await client.list_products(is_active=True)
        assert "Category" in result
        ok("list_products (active)", result)
        passed += 1
    except Exception as e:
        fail("list_products", str(e))
        failed += 1

    # 2. list_products (category filter)
    try:
        result = await client.list_products(category="Monitors", is_active=True)
        assert "Monitor" in result
        ok("list_products (Monitors category)", result)
        passed += 1
    except Exception as e:
        fail("list_products (category)", str(e))
        failed += 1

    # 3. search_products
    try:
        result = await client.search_products("ultrawide")
        assert "Ultrawide" in result or "ultrawide" in result.lower()
        ok("search_products('ultrawide')", result)
        passed += 1
    except Exception as e:
        fail("search_products", str(e))
        failed += 1

    # 4. get_product (known SKU)
    try:
        result = await client.get_product("MON-0054")
        assert "MON-0054" in result
        ok("get_product('MON-0054')", result)
        passed += 1
    except Exception as e:
        fail("get_product", str(e))
        failed += 1

    # 5. get_product — unknown SKU should raise ProductNotFoundError
    try:
        await client.get_product("INVALID-SKU-999")
        fail("get_product (bad SKU)", "Expected an error but got none")
        failed += 1
    except Exception:
        ok("get_product (bad SKU raises error)")
        passed += 1

    # 6. verify_customer_pin — wrong credentials
    try:
        await client.verify_customer_pin("nobody@example.com", "0000")
        fail("verify_customer_pin (bad creds)", "Expected CustomerNotFoundError")
        failed += 1
    except CustomerNotFoundError:
        ok("verify_customer_pin (bad creds raises CustomerNotFoundError)")
        passed += 1
    except Exception as e:
        ok(f"verify_customer_pin (bad creds raises error: {type(e).__name__})")
        passed += 1

    # 7. list_orders (no filter — returns all orders in system)
    try:
        result = await client.list_orders()
        ok("list_orders (no filter)", result)
        passed += 1
    except Exception as e:
        fail("list_orders", str(e))
        failed += 1

    # 8. call_tool generic interface
    try:
        result = await client.call_tool("search_products", {"query": "keyboard"})
        assert len(result) > 0
        ok("call_tool generic ('search_products')", result)
        passed += 1
    except Exception as e:
        fail("call_tool", str(e))
        failed += 1

    await client.stop()

    print(f"\n{'─' * 50}")
    print(f"Results: {GREEN}{passed} passed{RESET}, {RED if failed else ''}{failed} failed{RESET}")
    print()

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run())
