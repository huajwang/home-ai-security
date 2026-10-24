"""Task list for the phone and the printer."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from hub.ai.rkllm_bridge import get_runner
from hub.api.deps import current_principal, get_services
from hub.print.job import print_document
from hub.tasks.store import speak_open_tasks

router = APIRouter(prefix="/v1/tasks", tags=["tasks"])


class TaskBody(BaseModel):
    kind: str = "reminder"
    text: str


def _chat() -> Callable[..., str]:
    def chat(messages: list[dict[str, str]], max_new_tokens: int = 80, timeout: float = 25.0) -> str:
        runner = get_runner()
        if not runner.is_available:
            return ""
        return runner.chat(messages, max_new_tokens=max_new_tokens, timeout=timeout)

    return chat


@router.get("")
def list_tasks(
    _: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, Any]:
    tasks = services["tasks"].list_open()
    return {"tasks": tasks}


@router.post("")
def add_task(
    body: TaskBody,
    _: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, Any]:
    kind = body.kind if body.kind in {"reminder", "shopping", "maintenance"} else "reminder"
    return services["tasks"].add(kind, body.text, _chat())


@router.post("/{task_id}/done")
def finish_task(
    task_id: str,
    _: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, Any]:
    item = services["tasks"].mark_done(task_id)
    if item is None:
        return {"ok": False}
    return {"ok": True, "task": item}


@router.post("/print")
def print_tasks(
    _: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, Any]:
    tasks = services["tasks"].list_open()
    body = speak_open_tasks(tasks, True)
    return print_document("清单", body)
