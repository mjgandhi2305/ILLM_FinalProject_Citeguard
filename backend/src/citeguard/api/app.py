"""FastAPI application factory: `uvicorn citeguard.api.app:create_app --factory`."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from citeguard.api.routes import router
from citeguard.api.state import AppState
from citeguard.config import Settings, get_settings
from citeguard.db.repo import Repository
from citeguard.db.session import create_all, make_engine, make_sessionmaker
from citeguard.engine import Engine, LLMServices
from citeguard.observability.logging import configure_logging
from citeguard.sources.infra import Cache
from citeguard.sources.registry import SourceSet
from citeguard.worker.events import EventBus, LocalEventBus, RedisEventBus

log = structlog.get_logger(__name__)


async def _purge_loop(state: AppState, every_s: float = 6 * 3600) -> None:
    while True:
        try:
            removed = await state.repo.purge_expired()
            if removed:
                log.info("retention.purged", checks=removed)
        except Exception as exc:  # keep the loop alive
            log.warning("retention.purge_failed", error=str(exc))
        await asyncio.sleep(every_s)


def create_app(
    settings: Settings | None = None,
    *,
    sources: SourceSet | None = None,
    llm: LLMServices | None = None,
    cache: Cache | None = None,
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings.log_level, settings.log_json)
        db = make_engine(settings.database_url)
        if settings.db_auto_create:
            await create_all(db)
        engine = Engine(settings, sources=sources, llm=llm, cache=cache)
        await engine.__aenter__()
        bus: EventBus
        arq = None
        if settings.job_backend == "arq":
            from arq import create_pool
            from arq.connections import RedisSettings

            arq = await create_pool(RedisSettings.from_dsn(settings.redis_url))
            bus = RedisEventBus(settings.redis_url)
        else:
            bus = LocalEventBus()
        state = AppState(
            settings=settings,
            db=db,
            repo=Repository(make_sessionmaker(db)),
            engine=engine,
            bus=bus,
            arq=arq,
            check_slots=asyncio.Semaphore(settings.max_concurrent_checks),
        )
        app.state.cg = state
        purge: asyncio.Task[None] | None = None
        if arq is None:
            purge = asyncio.create_task(_purge_loop(state))
            for check_id in await state.repo.unfinished_checks():
                log.info("check.requeued_after_restart", check_id=str(check_id))
                await state.enqueue(check_id)
        log.info("app.started", job_backend=settings.job_backend, llm=engine.llm is not None)
        try:
            yield
        finally:
            if purge is not None:
                purge.cancel()
            # Graceful drain: let running checks finish; anything still running after the
            # grace period is cancelled and re-queued on the next start (input is kept).
            if state.tasks:
                await asyncio.wait(list(state.tasks), timeout=settings.shutdown_grace_s)
            for task in list(state.tasks):
                task.cancel()
            for task in [*state.tasks, *([purge] if purge else [])]:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            await engine.__aexit__(None, None, None)
            if isinstance(bus, RedisEventBus):
                await bus.close()
            if arq is not None:
                await arq.aclose()
            await db.dispose()

    app = FastAPI(
        title="CiteGuard API",
        version=settings.app_version,
        description=(
            "Detects fabricated and inaccurate citations, verifies them against scholarly "
            "databases, explains every verdict with evidence and suggests real alternatives."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "X-API-Key", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Content-Disposition", "Retry-After"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response

    app.include_router(router)

    @app.get("/healthz", tags=["ops"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", tags=["ops"])
    async def readyz(request: Request) -> Response:
        state: AppState = request.app.state.cg
        try:
            async with state.db.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception as exc:
            return Response(content=f"database unavailable: {exc}", status_code=503)
        return Response(content="ready", media_type="text/plain")

    @app.get("/metrics", tags=["ops"], include_in_schema=False)
    async def metrics() -> Response:
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app
