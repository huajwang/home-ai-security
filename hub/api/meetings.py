"""Meeting control. The satellite sends text; the phone reads the minutes."""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from hub.ai.rkllm_bridge import get_runner
from hub.api.deps import current_principal, get_services

router = APIRouter(prefix="/v1/meetings", tags=["meetings"])


class ChunkBody(BaseModel):
    text: str


def _chat() -> Callable[..., str]:
    def chat(messages: list[dict[str, str]], max_new_tokens: int = 120, timeout: float = 30.0) -> str:
        runner = get_runner()
        if not runner.is_available:
            return ""
        return runner.chat(messages, max_new_tokens=max_new_tokens, timeout=timeout)

    return chat


@router.post("/start")
def start_meeting(
    _: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, Any]:
    return services["meetings"].start()


@router.get("/active")
def active_meeting(
    _: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, Any]:
    return {"active": services["meetings"].active()}


@router.post("/active/chunks")
def add_chunk(
    body: ChunkBody,
    _: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, Any]:
    return services["meetings"].add_chunk(body.text, _chat())


@router.post("/stop")
def stop_meeting(
    _: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, Any]:
    """Ask the satellite to flush, then finish. Voice calls finish directly."""
    result = services["meetings"].request_stop()
    meeting_id = result.get("id")
    if result.get("state") == "stopping" and meeting_id:
        threading.Thread(
            target=_finish_if_still_stopping,
            args=(services["meetings"], meeting_id),
            daemon=True,
        ).start()
    return result


@router.post("/finish")
def finish_meeting(
    _: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, Any]:
    return services["meetings"].finish(_chat())


@router.get("")
def list_meetings(
    _: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, Any]:
    meetings = services["meetings"].list_meetings()
    return {"meetings": meetings, "latest": meetings[0] if meetings else None}


def _finish_if_still_stopping(meetings: Any, meeting_id: str) -> None:
    """Finish from the phone if the satellite does not flush in time."""
    time.sleep(25)
    active = meetings.active()
    if active and active.get("id") == meeting_id and active.get("state") == "stopping":
        meetings.finish(_chat())
