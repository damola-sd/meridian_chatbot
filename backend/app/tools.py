"""
OpenAI function-calling tool definitions for the Meridian chatbot agent.

Each description is written as an instruction to the LLM, not just
documentation — it tells the model *when* and *how* to use each tool.
"""

TOOLS: list[dict] = [
----------------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "list_products",
            "description": (
                "Browse the Meridian product catalog. Use this when the customer wants to see "
                "what products are available, browse by category, or explore the range without "
                "a specific keyword in mind. "
                "Valid categories: 'Computers', 'Monitors', 'Printers', 'Accessories', 'Networking'. "
                "Do NOT use this to find a specific product by name — use search_products instead. "
                "No authentication required."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": (
                            "Optional category filter. One of: "
                            "'Computers', 'Monitors', 'Printers', 'Accessories', 'Networking'."
                        ),
                    },
                    "is_active": {
                        "type": "boolean",
                        "description": "Filter by active status. Pass true to show only in-stock products.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": (
                "Search the catalog by keyword or product name. Use this when the customer mentions "
                "a specific type of product (e.g. 'ultrawide monitor', 'mechanical keyboard', "
                "'laser printer'). Returns matching products with prices and stock levels. "
                "Prefer this over list_products when the customer has a specific item in mind. "
                "No authentication required."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search keyword or product name. Case-insensitive, partial match.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product",
            "description": (
                "Get full details for a specific product by its SKU (e.g. 'MON-0054'). "
                "Use this when you already know the SKU and need to confirm the current price "
                "and stock level before presenting an order summary. "
                "No authentication required."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sku": {
                        "type": "string",
                        "description": "Product SKU, e.g. 'MON-0054', 'COM-0006', 'ACC-0132'.",
                    },
                },
                "required": ["sku"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "verify_customer_pin",
            "description": (
                "Authenticate a customer using their email address and 4-digit PIN. "
                "ALWAYS call this before accessing order history or placing an order. "
                "Ask the customer for their email and PIN before calling — never guess. "
                "On success, returns customer details including name and customer ID. "
                "On failure, a CustomerNotFoundError is raised — inform the customer politely "
                "and offer to try again. "
                "Once authenticated in a session, do NOT ask for credentials again."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "email": {
                        "type": "string",
                        "description": "Customer's email address.",
                    },
                    "pin": {
                        "type": "string",
                        "description": "Customer's 4-digit PIN code.",
                    },
                },
                "required": ["email", "pin"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_customer",
            "description": (
                "Retrieve a customer's profile by their customer ID. "
                "Only call this after the customer has been authenticated via verify_customer_pin. "
                "Use it to confirm account details like name and shipping address if the customer asks."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {
                        "type": "string",
                        "description": "Customer UUID obtained from a successful verify_customer_pin call.",
                    },
                },
                "required": ["customer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_orders",
            "description": (
                "List the order history for an authenticated customer. "
                "Requires the customer_id from a successful verify_customer_pin call — "
                "this is injected automatically from the session, do not ask the customer for it. "
                "Optionally filter by order status. "
                "Valid statuses: 'draft', 'submitted', 'approved', 'fulfilled', 'cancelled'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {
                        "type": "string",
                        "description": "Customer UUID. Injected from session — do not ask the customer.",
                    },
                    "status": {
                        "type": "string",
                        "description": (
                            "Optional status filter: "
                            "'draft', 'submitted', 'approved', 'fulfilled', or 'cancelled'."
                        ),
                    },
                },
                "required": ["customer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_order",
            "description": (
                "Get full details of a specific order, including all line items, quantities, "
                "and prices. Use when the customer asks about a particular order. "
                "Requires the order ID — obtain it from list_orders first if the customer "
                "does not provide it directly."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "Order UUID.",
                    },
                },
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_order",
            "description": (
                "Place a new order for an authenticated customer. "
                "STRICT RULES — only call this after ALL of the following: "
                "(1) the customer is authenticated via verify_customer_pin, "
                "(2) you have called get_product to confirm the current price and stock, "
                "(3) you have shown a clear order summary — product name, SKU, quantity, "
                "    unit price, and total cost, "
                "(4) the customer has explicitly said yes or confirmed they want to proceed. "
                "NEVER call create_order speculatively or without explicit confirmation. "
                "The server atomically validates inventory and decrements stock on success."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {
                        "type": "string",
                        "description": "Customer UUID. Injected from session — do not ask the customer.",
                    },
                    "items": {
                        "type": "array",
                        "description": "List of items to order.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "sku": {
                                    "type": "string",
                                    "description": "Product SKU, e.g. 'MON-0054'.",
                                },
                                "quantity": {
                                    "type": "integer",
                                    "description": "Number of units to order. Must be greater than 0.",
                                },
                                "unit_price": {
                                    "type": "string",
                                    "description": "Price per unit as a decimal string, e.g. '166.85'.",
                                },
                                "currency": {
                                    "type": "string",
                                    "description": "Currency code. Default is 'USD'.",
                                },
                            },
                            "required": ["sku", "quantity", "unit_price"],
                        },
                    },
                },
                "required": ["customer_id", "items"],
            },
        },
    },
]

TOOL_NAMES: set[str] = {t["function"]["name"] for t in TOOLS}
