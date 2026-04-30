from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1, description="Client-generated UUID for the session")
    message: str = Field(..., min_length=1, description="Customer's message text")


class HealthResponse(BaseModel):
    status: str
    active_sessions: int
    mcp_url: str
