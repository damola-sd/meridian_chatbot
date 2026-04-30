# Meridian Electronics AI Chatbot — Engineering Plan

**Project:** Meridian Customer Support Chatbot  
**Author:** Engineering Team  
**Date:** April 30, 2026  
**Status:** In Progress  

---

## 1. Overview

Meridian Electronics' support team currently handles all customer inquiries by phone and email.
This project delivers an AI-powered chatbot that handles the four most common request types:

- Checking product availability and browsing the catalog
- Authenticating returning customers
- Looking up order history
- Placing new orders

The backend team has already built and deployed an internal services layer exposed as an MCP
(Model Context Protocol) server. This project builds the AI conversation layer on top of that
existing infrastructure.

**MCP Server:** `https://order-mcp-74afyau24q-uc.a.run.app/mcp`  
**Transport:** Streamable HTTP (JSON-RPC 2.0)

---

## 2. Architecture

### High-Level Diagram

```
Customer Browser
      │
      │  HTTPS (SSE streaming)
      ▼
┌─────────────────┐
│   Next.js App   │  ← Vercel
│   (Frontend)    │
└────────┬────────┘
         │ POST /chat (SSE)
         ▼
┌─────────────────┐
│  FastAPI Agent  │  ← Railway
│   (Backend)     │
│                 │
│  ┌───────────┐  │
│  │  OpenAI   │  │  ← GPT-4o-mini (LLM with tool calling)
│  │  GPT-4o   │  │
│  └───────────┘  │
└────────┬────────┘
         │ JSON-RPC 2.0 (HTTP)
         ▼
┌─────────────────┐
│   MCP Server    │  ← Google Cloud Run (existing)
│  (order-mcp)    │
└─────────────────┘
```

### Technology Choices

| Layer | Technology | Hosting | Rationale |
|---|---|---|---|
| Frontend UI | Next.js 15 (App Router) + Tailwind CSS | Vercel | Zero-config deploys, SSE support, free tier |
| Backend / Agent | Python 3.12 + FastAPI | Railway | Fast to build, async-native, Docker support |
| LLM | OpenAI GPT-4o-mini | External API | Cost-efficient, strong tool calling, streaming support |
| Sessions | In-memory (dict) | Railway (same process) | Sufficient for single-instance MVP |
| Business Data | MCP Server (existing) | Google Cloud Run | Already built, not modified |

---

## 3. MCP Server Capabilities

The existing MCP server exposes 8 tools that map directly to the four business goals:

| Tool | Description | Auth Required |
|---|---|---|
| `list_products` | Browse catalog by category or active status | No |
| `get_product` | Get full details for a product by SKU | No |
| `search_products` | Search products by name/keyword | No |
| `verify_customer_pin` | Authenticate customer with email + 4-digit PIN | No |
| `get_customer` | Retrieve customer profile by ID | No |
| `list_orders` | List orders for a customer (filterable by status) | Yes |
| `get_order` | Get full order details including line items | Yes |
| `create_order` | Place a new order (atomic, validates inventory) | Yes |

Products span 5 categories: Computers, Monitors, Printers, Accessories, Networking.  
153 active products. Orders use statuses: `draft`, `submitted`, `approved`, `fulfilled`, `cancelled`.

---

## 4. Project Structure

```
meridian-chatbot/
│
├── backend/                        ← FastAPI application
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                 ← FastAPI app, routes, CORS, lifespan
│   │   ├── mcp_client.py           ← JSON-RPC HTTP client for MCP server
│   │   ├── tools.py                ← OpenAI function-calling tool definitions (8 tools)
│   │   ├── prompts.py              ← System prompt + business rules
│   │   ├── session.py              ← Session dataclass + in-memory store
│   │   ├── agent.py                ← LLM ReAct loop, async streaming generator
│   │   └── models.py               ← Pydantic request/response schemas
│   ├── tests/
│   │   ├── test_mcp_client.py
│   │   └── test_agent.py
│   ├── .env.example
│   ├── requirements.txt
│   └── Dockerfile
│
└── frontend/                       ← Next.js application
    ├── app/
    │   ├── layout.tsx
    │   ├── page.tsx                 ← Chat page
    │   └── globals.css
    ├── components/
    │   ├── ChatWindow.tsx           ← Message list + input form
    │   ├── Message.tsx              ← User/assistant message bubble
    │   └── QuickActions.tsx        ← Quick-start prompt chips
    ├── hooks/
    │   └── useChat.ts               ← SSE stream consumer + session state
    ├── lib/
    │   └── api.ts                   ← Typed fetch wrapper for backend
    ├── .env.local
    └── package.json
```

---

## 5. Build Plan

### Phase 0 — Environment Setup (15 min)

- Create monorepo directory structure
- Set up Python virtual environment
- Install backend dependencies: `fastapi`, `uvicorn`, `httpx`, `openai`, `python-dotenv`, `pydantic`
- Create `.env` with `OPENAI_API_KEY` and `MCP_SERVER_URL`

### Phase 1 — MCP Client (30 min)

**File:** `backend/app/mcp_client.py`

Implements a thin wrapper around the MCP server's JSON-RPC 2.0 protocol.

Key details:
- Uses `httpx.AsyncClient` with a shared instance (initialised at server startup via FastAPI `lifespan`)
- Sends `Accept: application/json, text/event-stream` header (required by server)
- Parses `result.content[0].text` from successful responses
- Raises typed Python exceptions for domain errors:
  - `ProductNotFoundError`
  - `CustomerNotFoundError`
  - `InsufficientInventoryError`
  - `MCPError` (generic fallback)

**Validation gate:** Test all 8 tools against the live MCP server with a standalone script before proceeding.

### Phase 2 — Tool Definitions (20 min)

**File:** `backend/app/tools.py`

Translates the 8 MCP tools into OpenAI function-calling schema format
(list of dicts with `type: "function"`, `function.name`, `function.description`, `function.parameters`).

The tool descriptions act as the LLM's decision-making instructions — not just documentation.
They encode rules such as:
- "Call `verify_customer_pin` before accessing order history or placing orders"
- "Never call `create_order` without explicit customer confirmation"
- "Use `search_products` for keyword lookups, `list_products` for category browsing"

### Phase 3 — System Prompt (30 min)

**File:** `backend/app/prompts.py`

Encodes all business rules in a structured system prompt. Key sections:

- **Identity:** Aria, Meridian Electronics support assistant
- **Authentication rules:** When to require PIN verification; once authenticated, do not ask again
- **Ordering rules:** Always show order summary and get explicit confirmation before `create_order`
- **Scope limits:** Returns, refunds, shipping issues → escalate to human team
- **Tone:** Warm, concise, professional; use bullet points for lists

### Phase 4 — Session Management (20 min)

**File:** `backend/app/session.py`

Manages per-conversation state:
- `customer_id` — set after successful `verify_customer_pin`
- `customer_name`, `customer_email` — for personalisation
- `history` — full OpenAI messages format for multi-turn context
- 30-minute idle TTL with automatic cleanup

Stored in a module-level dictionary (appropriate for single-instance deployment).
Can be swapped for Redis with no interface changes if horizontal scaling is needed.

### Phase 5 — Agent Loop (60 min)

**File:** `backend/app/agent.py`

Implements a **streaming ReAct loop**:

1. Append user message to session history
2. Call GPT-4o-mini with system prompt + full history + tool definitions (streaming)
3. Yield text chunks to caller as they arrive (real-time streaming to client)
4. On `finish_reason == "tool_calls"`: execute all requested tools via MCP client
5. Append tool results to history as `role: "tool"` messages and loop back to step 2
6. On `finish_reason == "stop"`: break — response is complete

Side effects handled in the loop:
- After `verify_customer_pin` succeeds: extract and store `customer_id` in session
- Before `list_orders` or `create_order`: auto-inject `customer_id` from session

### Phase 6 — FastAPI Application (30 min)

**File:** `backend/app/main.py`

Endpoints:
- `GET /health` — health check for Railway deployment probes
- `POST /chat` — main chat endpoint, returns `text/event-stream` SSE response

SSE event format:
```
data: {"text": "chunk of response text"}\n\n
data: {"error": "error message"}\n\n   ← on failure
data: [DONE]\n\n                        ← stream complete
```

CORS middleware configured to allow requests from the Next.js frontend origin.
MCP client lifecycle managed via FastAPI `lifespan` context manager.

### Phase 7 — Backend Testing (30 min)

Validate all use cases with `curl` before building the frontend:

1. Health check
2. Browse products — no auth required
3. Search products by keyword
4. Request order history → agent asks for credentials
5. Provide email + PIN → agent authenticates and shows orders
6. Place an order → confirmation flow → `create_order`
7. Wrong PIN → graceful error message
8. Out-of-stock item → alternative suggestions

**The backend is complete when all 8 test cases pass.**

---

### Phase 8 — Next.js Scaffold (20 min)

Bootstrap with:
```bash
npx create-next-app@latest frontend --typescript --tailwind --app
```

Install additional dependencies:
- `uuid` — client-side session ID generation

Configure `NEXT_PUBLIC_API_URL` in `.env.local`.

### Phase 9 — UI Components (45 min)

**`Message.tsx`**
- User messages: right-aligned, brand-colour background
- Assistant messages: left-aligned, light background, renders markdown
- Loading indicator while streaming

**`QuickActions.tsx`**
- Four pre-fill chips: "Browse products", "Search monitors", "My orders", "Place an order"
- Disappear after first message is sent

**`ChatWindow.tsx`**
- Renders scrollable message list (auto-scrolls to bottom on new messages)
- Text input + send button
- Disables input while streaming is active
- Shows "Aria is typing…" indicator during streaming

### Phase 10 — useChat Hook (30 min)

**File:** `frontend/hooks/useChat.ts`

Encapsulates all SSE logic and session management:
- Session ID generated with `crypto.randomUUID()` on first load, persisted in `sessionStorage`
- Sends POST to `/chat` with `session_id` + `message`
- Reads SSE stream, accumulates text chunks into assistant message
- Updates React state on each chunk (progressive rendering)
- Handles `[DONE]` and `error` events

### Phase 11 — Wire Frontend to Backend (20 min)

- Connect `useChat` hook to `ChatWindow` component in `app/page.tsx`
- Add Meridian branding to the header
- Verify end-to-end flow in development (`localhost:3000` → `localhost:8000`)

---

## 6. Deployment

### Backend — Railway

1. Add `Dockerfile` to `backend/`
2. `railway login && railway init && railway up`
3. Set environment variables in Railway dashboard:
   - `OPENAI_API_KEY`
   - `MCP_SERVER_URL`
   - `ALLOWED_ORIGINS` (Vercel frontend URL)

Output: `https://meridian-backend-production.up.railway.app`

### Frontend — Vercel

1. Push to GitHub
2. Import repository at `vercel.com/new`
3. Set environment variable:
   - `NEXT_PUBLIC_API_URL` (Railway backend URL)
4. `vercel --prod`

Output: `https://meridian-chatbot.vercel.app`

---

## 7. Security Considerations

| Concern | Mitigation |
|---|---|
| PIN exposure in logs | Strip `verify_customer_pin` arguments from all logs |
| Session hijacking | Session IDs are UUIDs; 30-minute TTL enforced server-side |
| Unauthorised order access | `customer_id` injected from server-side session, never trusted from client |
| Accidental orders | LLM instructed to always confirm before calling `create_order` |
| Scope creep | System prompt explicitly refuses out-of-scope requests |
| CORS | Backend only allows requests from the configured frontend origin |

---

## 8. Known Limitations (MVP Scope)

- Sessions are in-memory — restarting the backend clears all sessions
- No payment processing (orders are placed in `submitted` status, pending fulfilment)
- No file/image support — text-only conversation
- No human handoff integration (currently directs customers to email/phone)
- Single LLM provider — no fallback if OpenAI is unavailable

---

## 9. Future Improvements (Post-MVP)

- Replace in-memory sessions with Redis (Upstash) for multi-instance support
- Add conversation rating / feedback widget
- Implement human escalation handoff via webhook to support ticketing system
- Add order tracking status updates (requires new MCP tool)
- Analytics dashboard for deflection rate, common queries, failure cases

---

## 10. Timeline

| Phase | Task | Estimated Time |
|---|---|---|
| 0 | Environment setup | 15 min |
| 1 | MCP client | 30 min |
| 2 | Tool definitions | 20 min |
| 3 | System prompt | 30 min |
| 4 | Session management | 20 min |
| 5 | Agent loop | 60 min |
| 6 | FastAPI application | 30 min |
| 7 | Backend testing | 30 min |
| 8 | Next.js scaffold | 20 min |
| 9 | UI components | 45 min |
| 10 | useChat hook | 30 min |
| 11 | Wire frontend to backend | 20 min |
| 12 | Deploy | 20 min |
| **Total** | | **~6 hours** |
