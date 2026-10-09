"""FastAPI endpoint for the Local Voice AI Assistant."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from hub import config
from hub.ai.assistant import AssistantEngine
from hub.ai.rkllm_bridge import get_runner
from hub.api.deps import current_principal, get_services

router = APIRouter(prefix="/v1/assistant", tags=["assistant"])


class AssistantChatRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=1000)
    history: Optional[list[dict[str, str]]] = None


@router.get("/status")
def get_assistant_status(
    _: dict[str, Any] = Depends(current_principal),
) -> dict[str, Any]:
    runner = get_runner()
    return {
        "enabled": config.ASSISTANT_ENABLED,
        "npu_llm_available": runner.is_available,
        "model_path": config.RKLLM_MODEL_PATH,
    }


@router.post("/chat")
def assistant_chat(
    payload: AssistantChatRequest,
    principal: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, Any]:
    username = principal.get("user", {}).get("username", "voice_satellite")
    engine = AssistantEngine(services=services, actor=username)
    result = engine.process_query(prompt=payload.prompt, history=payload.history)
    return result
