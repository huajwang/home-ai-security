"""Notes, pictures, search, and printing for the library page."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from hub.ai.rkllm_bridge import get_runner
from hub.api.deps import current_principal, get_services
from hub.errors import raise_api
from hub.print.job import print_document

router = APIRouter(prefix="/v1/library", tags=["library"])


class NoteBody(BaseModel):
    text: str
    title: str = ""


class ChunkBody(BaseModel):
    text: str


def _chat() -> Callable[..., str]:
    def chat(messages: list[dict[str, str]], max_new_tokens: int = 40, timeout: float = 25.0) -> str:
        runner = get_runner()
        if not runner.is_available:
            return ""
        return runner.chat(messages, max_new_tokens=max_new_tokens, timeout=timeout)

    return chat


def _public(note: dict[str, Any]) -> dict[str, Any]:
    note_id = note.get("id")
    pictures = [
        f"/v1/library/notes/{note_id}/pictures/{name}"
        for name in (note.get("pictures") or [])
    ]
    return {
        "id": note_id,
        "title": note.get("title") or "",
        "body": note.get("body") or "",
        "created_at": note.get("created_at"),
        "pictures": pictures,
    }


@router.get("/notes")
def list_notes(
    q: str = "",
    _: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, Any]:
    notes = services["library"].search(q)
    return {"notes": [_public(note) for note in notes]}


@router.post("/notes")
def create_note(
    body: NoteBody,
    _: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, Any]:
    saved = services["library"].add_text(body.text, body.title, _chat())
    if not saved.get("ok", True) and saved.get("message") == "empty":
        raise_api(400, "empty", "The note is empty.")
    return _public(saved)


@router.get("/active")
def active_note(
    _: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, Any]:
    return {"active": services["library"].active()}


@router.post("/active/chunks")
def add_chunk(
    body: ChunkBody,
    _: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, Any]:
    return services["library"].add_chunk(body.text)


@router.post("/notes/{note_id}/pictures")
async def add_picture(
    note_id: str,
    file: UploadFile = File(...),
    _: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, Any]:
    data = await file.read()
    if len(data) > 8 * 1024 * 1024:
        raise_api(400, "too_large", "A picture must be 8 MB or smaller.")
    note = services["library"].add_picture(note_id, file.filename or "picture.jpg", data)
    if note is None:
        raise_api(404, "not_found", "That note does not exist.")
    return _public(note)


@router.get("/notes/{note_id}/pictures/{name}")
def get_picture(
    note_id: str,
    name: str,
    _: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> FileResponse:
    path = services["library"].picture_path(note_id, name)
    if path is None:
        raise_api(404, "not_found", "That picture does not exist.")
    return FileResponse(path)


@router.post("/notes/{note_id}/print")
def print_note(
    note_id: str,
    _: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, Any]:
    note = services["library"].get(note_id)
    if note is None:
        raise_api(404, "not_found", "That note does not exist.")
    pictures = []
    for name in note.get("pictures") or []:
        path = services["library"].picture_path(note_id, name)
        if path is not None:
            pictures.append(path)
    return print_document(note.get("title") or "Note", note.get("body") or "", pictures)
