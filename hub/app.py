"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from hub import config
from hub.api import auth, calls, events, lock, system
from hub.auth import bootstrap_owner
from hub.devices.lock import build_lock_adapter
from hub.errors import http_error_handler
from hub.media.webrtc import CallManager
from hub.notify import EventBus
from hub.ratelimit import RateLimiter
from hub.state import HubState
from hub.storage import Store
from hub.vision.worker import VisionWorker


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.ensure_dirs()
    store = Store()
    bootstrap_owner(store)
    state = HubState()
    bus = EventBus()
    lock_adapter = build_lock_adapter(store)
    vision = VisionWorker(store, state, bus)
    calls_mgr = CallManager(vision)

    app.state.store = store
    app.state.hub_state = state
    app.state.bus = bus
    app.state.lock = lock_adapter
    app.state.vision = vision
    app.state.calls = calls_mgr
    app.state.login_limiter = RateLimiter(config.LOGIN_RATE_LIMIT)
    app.state.unlock_limiter = RateLimiter(config.UNLOCK_RATE_LIMIT)

    vision.start(asyncio_loop())
    yield
    vision.stop()


def asyncio_loop():
    import asyncio

    return asyncio.get_running_loop()


def create_app() -> FastAPI:
    app = FastAPI(title="Home AI Security Hub", version="0.1.0", lifespan=lifespan)
    app.add_exception_handler(HTTPException, http_error_handler)
    app.include_router(auth.router)
    app.include_router(system.router)
    app.include_router(events.router)
    app.include_router(lock.router)
    app.include_router(calls.router)

    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/dev/call", response_class=HTMLResponse)
    def dev_call() -> FileResponse:
        page = static_dir / "call.html"
        if not page.is_file():
            return HTMLResponse("<p>Dev call page missing.</p>", status_code=404)
        return FileResponse(page)

    return app


app = create_app()
