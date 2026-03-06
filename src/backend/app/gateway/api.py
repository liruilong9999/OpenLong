from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    agent_id: str
    reply: str


def build_api_router() -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    async def health(request: Request) -> dict[str, str]:
        endpoint = request.app.state.runtime.model_router.endpoint_for("main")
        return {
            "status": "ok",
            "provider": endpoint.provider,
            "model": endpoint.model,
            "key_configured": str(endpoint.has_api_key).lower(),
        }

    @router.get("/sessions")
    async def list_sessions(request: Request) -> list[dict[str, str | int]]:
        return request.app.state.runtime.session_manager.list_sessions()

    @router.post("/chat", response_model=ChatResponse)
    async def chat(body: ChatRequest, request: Request) -> ChatResponse:
        session_id = body.session_id or str(uuid4())
        result = await request.app.state.runtime.handle_user_message(session_id, body.message)
        return ChatResponse(**result)

    return router
