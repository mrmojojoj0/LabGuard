from contextlib import asynccontextmanager
import asyncio
import logging
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text

from labguard_server.api import router
from labguard_server.config import Settings
from labguard_server.db import make_session_factory
from labguard_server.events import AdminEventHub
from labguard_server.websocket import router as websocket_router, status_monitor, telemetry_retention_monitor


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        settings.validate()
        engine, factory = make_session_factory(settings.database_url)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        application.state.engine = engine
        application.state.session_factory = factory
        application.state.admin_events = AdminEventHub()
        application.state.admin_events.bind(asyncio.get_running_loop())
        application.state.active_devices = {}
        monitor = asyncio.create_task(status_monitor(application))
        telemetry_monitor = asyncio.create_task(telemetry_retention_monitor(application))
        try:
            yield
        finally:
            monitor.cancel()
            telemetry_monitor.cancel()
            try:
                await monitor
            except asyncio.CancelledError:
                pass
            try:
                await telemetry_monitor
            except asyncio.CancelledError:
                pass
            engine.dispose()

    application = FastAPI(title="LabGuard Server", version="0.1.0", lifespan=lifespan)
    application.state.settings = settings
    application.include_router(router)
    application.include_router(websocket_router)

    @application.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request.state.request_id = request.headers.get("x-request-id", str(uuid4()))[:100]
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        fields = [{"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]} for error in exc.errors()]
        return JSONResponse(status_code=422, content={"error": {"code": "validation_error", "message": "Request validation failed",
                                  "request_id": request.state.request_id, "details": fields}})

    from fastapi import HTTPException

    @application.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException):
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail:
            code, message, details = detail["code"], detail["message"], detail.get("details", {})
        else:
            code, message, details = "http_error", str(detail), {}
        headers = exc.headers or {}
        return JSONResponse(status_code=exc.status_code, content={"error": {"code": code, "message": message,
                                   "request_id": request.state.request_id, "details": details}}, headers=headers)

    @application.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception):
        logging.getLogger("labguard_server").exception("Unhandled request error", exc_info=exc)
        return JSONResponse(status_code=500, content={"error": {"code": "internal_error", "message": "Internal server error",
                                   "request_id": request.state.request_id, "details": {}}})

    @application.get("/api/v1/health/live")
    def live():
        return {"status": "ok"}

    @application.get("/api/v1/health/ready")
    def ready(request: Request):
        engine = getattr(request.app.state, "engine", None)
        if engine is None:
            return JSONResponse(status_code=503, content={"status": "not_ready"})
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ready"}

    return application


app = create_app()
