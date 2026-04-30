# Meridian Electronics — AI Customer Support Chatbot

An AI-powered chatbot that handles common customer requests for Meridian Electronics: browsing the product catalogue, authenticating returning customers, looking up order history, and placing new orders.

---

## Architecture

```
Customer Browser
      │
      │  HTTPS (SSE streaming)
      ▼
┌─────────────────┐
│   Next.js App   │  ← Vercel
│   (Frontend)    │
└────────┬────────┘
         │ POST /chat  (SSE)
         ▼
┌─────────────────┐
│  FastAPI Agent  │  ← Render / Railway
│   (Backend)     │
│                 │
│  ┌───────────┐  │
│  │  OpenAI   │  │  GPT-4o-mini (tool calling)
│  │ GPT-4o-m  │  │
│  └───────────┘  │
└────────┬────────┘
         │ JSON-RPC 2.0 (HTTP)
         ▼
┌─────────────────┐
│   MCP Server    │  ← Google Cloud Run (existing)
│  (order-mcp)    │
└─────────────────┘
```

| Layer | Technology | Responsibility |
|---|---|---|
| Frontend | Next.js 15, Tailwind CSS | Chat UI, SSE stream consumer |
| Backend | FastAPI, Python 3.12 | Agent loop, session state, CORS |
| LLM | OpenAI GPT-4o-mini | Natural language + tool calling |
| Services | MCP Server (JSON-RPC 2.0) | Products, orders, auth |

---

## Project Structure

```
meridian/
├── Dockerfile                  # Root Dockerfile (used by Render)
├── render.yaml                 # Render IaC config
├── Plan.md                     # Engineering design document
│
├── backend/
│   ├── app/
│   │   ├── main.py             # FastAPI app, /chat SSE endpoint, /health
│   │   ├── agent.py            # Streaming ReAct loop (OpenAI tool calling)
│   │   ├── mcp_client.py       # JSON-RPC 2.0 client for the MCP server
│   │   ├── tools.py            # 8 MCP tools in OpenAI function-calling schema
│   │   ├── prompts.py          # System prompt — Aria's personality and rules
│   │   ├── session.py          # In-memory session store with TTL
│   │   └── models.py           # Pydantic request/response models
│   ├── tests/
│   │   ├── test_agent.py       # Unit tests for the agent loop (27 tests)
│   │   └── test_mcp_client.py  # Integration tests against live MCP server
│   ├── Dockerfile              # Standalone backend Dockerfile
│   ├── requirements.txt
│   ├── requirements-test.txt
│   ├── pytest.ini
│   └── .env.example
│
└── frontend/
    ├── app/
    │   ├── page.tsx            # Main chat page
    │   └── layout.tsx          # App shell, metadata
    ├── components/
    │   ├── ChatWindow.tsx      # Message list, input, auto-scroll
    │   ├── Message.tsx         # Individual message (markdown, avatars)
    │   └── QuickActions.tsx    # Quick-start prompt chips
    ├── hooks/
    │   └── useChat.ts          # SSE stream consumer, session ID management
    └── lib/
        └── api.ts              # Backend API client
```

---

## Local Development

### Prerequisites

- Python 3.12+
- Node.js 18+
- An [OpenAI API key](https://platform.openai.com/api-keys)

### Backend

```bash
cd backend

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and set OPENAI_API_KEY

# Start the server
uvicorn app.main:app --reload --port 8000
```

The API is now available at `http://localhost:8000`.

**Health check:**
```bash
curl http://localhost:8000/health
```

**Send a chat message:**
```bash
curl -N -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id": "test-123", "message": "What monitors do you have in stock?"}'
```

### Frontend

```bash
cd frontend

npm install

# Configure environment
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local

npm run dev
```

The UI is available at `http://localhost:3000`.

---

## Running Tests

```bash
cd backend

# Install test dependencies
pip install -r requirements-test.txt

# Run all unit tests
pytest tests/test_agent.py -v

# Run live integration tests (requires network access to MCP server)
python -m tests.test_mcp_client
```

The unit test suite (27 tests) uses mocked OpenAI and MCP clients — no API keys or network access required.

---

## Environment Variables

### Backend (`backend/.env`)

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | Yes | OpenAI API key |
| `MCP_SERVER_URL` | Yes | Meridian MCP server URL |
| `ALLOWED_ORIGINS` | No | Comma-separated CORS origins (default: `*`) |

### Frontend (`frontend/.env.local`)

| Variable | Required | Description |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | Yes | Backend base URL |

---

## Deployment

### Backend → Render

The root `Dockerfile` and `render.yaml` are configured for Render deployment.

1. Push the repository to GitHub
2. In the Render dashboard: **New → Web Service → Connect repository**
3. Render will detect `render.yaml` automatically
4. Set the `OPENAI_API_KEY` secret in **Environment → Secret Files**
5. Deploy

Alternatively, configure manually:
- **Runtime:** Docker
- **Dockerfile Path:** `./Dockerfile`
- **Docker Build Context:** `./` (repo root)

### Frontend → Vercel

```bash
cd frontend
npx vercel --prod
```

Set `NEXT_PUBLIC_API_URL` to your Render backend URL in the Vercel project settings.

---

## Key Design Decisions

**Streaming over SSE** — Responses are streamed token-by-token so customers see output immediately rather than waiting for the full reply.

**Server-side session state** — The frontend generates a UUID session ID; the backend holds all conversation history and authentication state. The client never touches customer UUIDs or PINs directly.

**Customer ID injection** — When calling protected tools (`list_orders`, `create_order`, `get_customer`), the backend silently injects the `customer_id` from the verified session. The LLM never asks the customer for their internal ID.

**Typed MCP exceptions** — `mcp_client.py` raises `ProductNotFoundError`, `CustomerNotFoundError`, and `InsufficientInventoryError` so the agent can phrase failures gracefully rather than surfacing raw server errors.

**In-memory sessions with TTL** — Sessions expire after 30 minutes of inactivity. The store can be replaced with Redis for horizontal scaling without changing the `Session` interface.

---

## API Reference

### `GET /health`

Returns service status and active session count.

```json
{
  "status": "ok",
  "active_sessions": 3,
  "mcp_url": "https://order-mcp-74afyau24q-uc.a.run.app/mcp"
}
```

### `POST /chat`

Sends a message and streams the response via SSE.

**Request body:**
```json
{
  "session_id": "uuid-string",
  "message": "Do you have any mechanical keyboards?"
}
```

**Response:** `text/event-stream` — each event is a JSON object:

```
data: {"type": "chunk", "content": "Yes, we carry"}
data: {"type": "chunk", "content": " several mechanical keyboards."}
data: {"type": "done"}
```

On error:
```
data: {"type": "error", "content": "Something went wrong. Please try again."}
```
