"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from hub import config
from hub.api import assistant, auth, calls, driveway, events, lights, lock, system
from hub.auth import bootstrap_owner
from hub.devices.doorbell import DoorbellWorker
from hub.devices.driveway import DrivewayCamera
from hub.devices.lock import build_lock_adapter
from hub.devices.zigbee_light import ZigbeeLights
from hub.errors import http_error_handler
from hub.media.webrtc import CallManager
from hub.monitor import MonitorPublisher
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
    bulb = ZigbeeLights()
    vision = VisionWorker(store, state, bus)
    vision.lights = bulb
    doorbell = DoorbellWorker(store, bus, vision)
    driveway_cam = DrivewayCamera(store, bus)
    calls_mgr = CallManager(vision)
    monitor = MonitorPublisher(vision, driveway_cam)

    app.state.store = store
    app.state.hub_state = state
    app.state.bus = bus
    app.state.lock = lock_adapter
    app.state.lights = bulb
    app.state.vision = vision
    app.state.driveway = driveway_cam
    app.state.calls = calls_mgr
    app.state.login_limiter = RateLimiter(config.LOGIN_RATE_LIMIT)
    app.state.unlock_limiter = RateLimiter(config.UNLOCK_RATE_LIMIT)

    loop = asyncio_loop()
    bulb.start()
    vision.start(loop)
    doorbell.start(loop)
    driveway_cam.start(loop)
    monitor.start()
    yield
    monitor.stop()
    driveway_cam.stop()
    doorbell.stop()
    vision.stop()
    bulb.stop()


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
    app.include_router(lights.router)
    app.include_router(driveway.router)
    app.include_router(calls.router)
    app.include_router(assistant.router)

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
