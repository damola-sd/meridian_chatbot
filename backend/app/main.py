import json
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from app.agent import run_agent
from app.mcp_client import MCPClient
from app.models import ChatRequest, HealthResponse
from app.session import active_count, cleanup_expired, get_or_create

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App-level singletons (initialised in lifespan)
# ---------------------------------------------------------------------------

mcp_client: MCPClient | None = None
openai_api_key: str = ""
mcp_server_url: str = ""


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mcp_client, openai_api_key, mcp_server_url

    openai_api_key = os.environ["OPENAI_API_KEY"]
    mcp_server_url = os.getenv("MCP_SERVER_URL", "https://order-mcp-74afyau24q-uc.a.run.app/mcp")

    mcp_client = MCPClient(mcp_server_url)
    await mcp_client.start()
    logger.info("MCP client ready — %s", mcp_server_url)

    yield

    await mcp_client.stop()
    logger.info("MCP client stopped")


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Meridian Chatbot API",
    description="AI customer support agent for Meridian Electronics",
    version="1.0.0",
    lifespan=lifespan,
)

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Max-Age": "86400",
}


@app.middleware("http")
async def cors_middleware(request: Request, call_next):
    """
    Simple manual CORS middleware — handles preflight and injects
    CORS headers on every response. Replaces Starlette CORSMiddleware
    which has edge-case issues with wildcard origins in 0.38.x.
    """
    if request.method == "OPTIONS":
        return Response(status_code=200, headers=CORS_HEADERS)

    response = await call_next(request)
    for key, value in CORS_HEADERS.items():
        response.headers[key] = value
    return response


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    cleanup_expired()
    return HealthResponse(
        status="ok",
        active_sessions=active_count(),
        mcp_url=mcp_server_url,
    )


@app.post("/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    if mcp_client is None:
        raise HTTPException(status_code=503, detail="Service not ready")

    session = get_or_create(req.session_id)

    async def event_stream():
        try:
            async for chunk in run_agent(session, req.message, mcp_client, openai_api_key):
                yield f"data: {json.dumps({'text': chunk})}\n\n"
        except Exception as exc:
            logger.exception("Unhandled error in agent for session %s", req.session_id)
            yield f"data: {json.dumps({'error': 'Something went wrong. Please try again.'})}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
