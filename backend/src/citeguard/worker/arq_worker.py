"""ARQ worker: `arq citeguard.worker.arq_worker.WorkerSettings`."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings

from citeguard.config import get_settings
from citeguard.db.repo import Repository
from citeguard.db.session import create_all, make_engine, make_sessionmaker
from citeguard.engine import Engine
from citeguard.observability.logging import configure_logging
from citeguard.sources.infra import RedisCache, RedisTokenBucket
from citeguard.worker.events import RedisEventBus
from citeguard.worker.runner import execute_check


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    db = make_engine(settings.database_url)
    if settings.db_auto_create:
        await create_all(db)
    redis = ctx["redis"]
    engine = Engine(
        settings,
        cache=RedisCache(settings.redis_url),
        # all workers share each scholarly source's quota
        limiter_factory=lambda name, rate: RedisTokenBucket(redis, name, rate),
    )
    await engine.__aenter__()
    ctx.update(
        db=db,
        engine=engine,
        repo=Repository(make_sessionmaker(db)),
        bus=RedisEventBus(settings.redis_url),
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["engine"].__aexit__(None, None, None)
    await ctx["bus"].close()
    await ctx["db"].dispose()


async def run_check(ctx: dict[str, Any], check_id: str) -> None:
    await execute_check(uuid.UUID(check_id), engine=ctx["engine"], repo=ctx["repo"], bus=ctx["bus"])


async def purge_expired(ctx: dict[str, Any]) -> int:
    count: int = await ctx["repo"].purge_expired()
    return count


class WorkerSettings:
    functions: ClassVar[list[Any]] = [run_check]
    cron_jobs: ClassVar[list[Any]] = [cron(purge_expired, hour={3}, minute={17})]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = get_settings().max_concurrent_checks
    job_timeout = 60 * 60
    job_completion_wait = 30  # graceful drain on SIGTERM; cancelled jobs are retried
