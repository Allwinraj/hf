from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.core.llm import build_llm_provider
from app.core.logging import bind_request, clear_context, configure_logging, get_logger
from app.core.settings import get_settings
from app.core.storage import Storage
from app.api.agents import router as agents_router
from app.api.chat import router as chat_router
from app.api.pipelines import router as pipelines_router
from app.api.runs import router as runs_router
import app.agents  # noqa: F401 — register specialist agents
from app.agents import registry as agent_registry

log = get_logger("nexus.api")

UI_ORIGIN = "https://nexus-ui.cfapps.eu10-004.hana.ondemand.com"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    app.state.settings = settings
    app.state.storage = Storage(settings.data_dir)
    app.state.llm = build_llm_provider(settings)
    app.state.registry = agent_registry
    log.info("nexus backend starting provider=%s", settings.llm_provider)
    yield
    log.info("nexus backend stopping")


app = FastAPI(title="Nexus 2.0", version="0.1.0", lifespan=lifespan)

app.include_router(chat_router)
app.include_router(agents_router)
app.include_router(pipelines_router)
app.include_router(runs_router)


@app.middleware("http")
async def correlation_middleware(request: Request, call_next):
    incoming = request.headers.get("x-request-id") or request.headers.get("x-correlation-id")
    request_id = bind_request(incoming)
    try:
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        response.headers["x-correlation-id"] = request_id
        return response
    finally:
        clear_context()


@app.get("/health")
async def health() -> dict[str, str]:
    settings = get_settings()
    return {"status": "ok", "provider": settings.llm_provider}


# CORS last so it wraps every response (including OPTIONS preflight).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        UI_ORIGIN,
        "*",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def create_app() -> FastAPI:
    return app
