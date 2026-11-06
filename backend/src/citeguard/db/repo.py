"""Data access for checks, citations, feedback and API keys."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from citeguard.db.models import ApiKey, Check, CheckInput, CitationRow, Feedback
from citeguard.domain.models import CitationResult

KEY_PREFIX = "cg_"


def hash_key(raw: str) -> str:
    # API keys are 256-bit random tokens, so a fast hash is appropriate (no brute-force risk).
    return hashlib.sha256(raw.encode()).hexdigest()


def new_api_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def keys_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


class Repository:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self.sm = sessionmaker

    # --- api keys ------------------------------------------------------------------------
    async def create_api_key(self, name: str, rate_limit_per_min: int = 30) -> tuple[ApiKey, str]:
        raw = new_api_key()
        row = ApiKey(
            name=name,
            key_hash=hash_key(raw),
            prefix=raw[:10],
            rate_limit_per_min=rate_limit_per_min,
        )
        async with self.sm() as s:
            s.add(row)
            await s.commit()
        return row, raw

    async def find_api_key(self, raw: str) -> ApiKey | None:
        async with self.sm() as s:
            row = await s.scalar(select(ApiKey).where(ApiKey.key_hash == hash_key(raw)))
            if row is None or row.revoked_at is not None:
                return None
            return row

    # --- checks --------------------------------------------------------------------------
    async def create_check(
        self,
        *,
        input_kind: str,
        content: bytes,
        options: dict[str, Any],
        filename: str | None,
        owner_key_id: uuid.UUID | None,
        retention_days: int,
        pipeline_version: str,
    ) -> Check:
        check = Check(
            input_kind=input_kind,
            filename=filename,
            options=options,
            owner_key_id=owner_key_id,
            pipeline_version=pipeline_version,
            expires_at=datetime.now(UTC) + timedelta(days=retention_days),
        )
        check.input = CheckInput(content=content)
        async with self.sm() as s:
            s.add(check)
            await s.commit()
        return check

    async def get_check(
        self, check_id: uuid.UUID, *, owner_key_id: uuid.UUID | None = None, with_rows: bool = True
    ) -> Check | None:
        async with self.sm() as s:
            stmt = select(Check).where(Check.id == check_id)
            if owner_key_id is not None:
                stmt = stmt.where(Check.owner_key_id == owner_key_id)
            if with_rows:
                stmt = stmt.options(selectinload(Check.citations))
            return await s.scalar(stmt)

    async def list_checks(self, owner_key_id: uuid.UUID | None, limit: int = 50) -> list[Check]:
        async with self.sm() as s:
            stmt = select(Check).order_by(Check.created_at.desc()).limit(limit)
            if owner_key_id is not None:
                stmt = stmt.where(Check.owner_key_id == owner_key_id)
            return list(await s.scalars(stmt))

    async def unfinished_checks(self) -> list[uuid.UUID]:
        """Checks interrupted by a restart: not finished and their input still stored."""
        async with self.sm() as s:
            rows = await s.scalars(
                select(Check.id)
                .join(CheckInput, CheckInput.check_id == Check.id)
                .where(Check.status.in_(("queued", "running")))
                .order_by(Check.created_at)
            )
            return list(rows)

    async def load_input(self, check_id: uuid.UUID) -> bytes | None:
        async with self.sm() as s:
            row = await s.get(CheckInput, check_id)
            return row.content if row else None

    async def mark_running(self, check_id: uuid.UUID) -> None:
        async with self.sm() as s:
            await s.execute(
                update(Check)
                .where(Check.id == check_id)
                .values(status="running", started_at=datetime.now(UTC))
            )
            await s.commit()

    async def set_total(self, check_id: uuid.UUID, total: int) -> None:
        async with self.sm() as s:
            await s.execute(update(Check).where(Check.id == check_id).values(progress_total=total))
            await s.commit()

    async def save_citation(self, check_id: uuid.UUID, result: CitationResult) -> int:
        """Upsert one citation result; returns the number of citations saved so far."""
        payload = result.model_dump(mode="json")
        async with self.sm() as s:
            row = await s.scalar(
                select(CitationRow).where(
                    CitationRow.check_id == check_id, CitationRow.ordinal == result.index
                )
            )
            if row is None:
                row = CitationRow(check_id=check_id, ordinal=result.index)
                s.add(row)
            row.verdict = result.verdict.value
            row.confidence = result.confidence
            row.risk_score = result.risk_score
            row.enriched = result.enriched
            row.result = payload
            await s.flush()
            done = len(
                list(
                    await s.scalars(select(CitationRow.id).where(CitationRow.check_id == check_id))
                )
            )
            await s.execute(update(Check).where(Check.id == check_id).values(progress_done=done))
            await s.commit()
            return done

    async def complete(
        self, check_id: uuid.UUID, summary: dict[str, Any], warnings: list[str]
    ) -> None:
        async with self.sm() as s:
            await s.execute(
                update(Check)
                .where(Check.id == check_id)
                .values(
                    status="completed",
                    summary=summary,
                    warnings=warnings,
                    completed_at=datetime.now(UTC),
                )
            )
            await s.execute(delete(CheckInput).where(CheckInput.check_id == check_id))
            await s.commit()

    async def fail(self, check_id: uuid.UUID, error: str) -> None:
        async with self.sm() as s:
            await s.execute(
                update(Check)
                .where(Check.id == check_id)
                .values(status="failed", error=error[:2000], completed_at=datetime.now(UTC))
            )
            await s.execute(delete(CheckInput).where(CheckInput.check_id == check_id))
            await s.commit()

    async def delete_check(self, check_id: uuid.UUID, owner_key_id: uuid.UUID | None) -> bool:
        async with self.sm() as s:
            stmt = select(Check).where(Check.id == check_id)
            if owner_key_id is not None:
                stmt = stmt.where(Check.owner_key_id == owner_key_id)
            check = await s.scalar(stmt)
            if check is None:
                return False
            await s.delete(check)
            await s.commit()
            return True

    async def purge_expired(self, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        async with self.sm() as s:
            res = await s.execute(delete(Check).where(Check.expires_at < now))
            await s.commit()
            return int(res.rowcount or 0)  # type: ignore[attr-defined]

    # --- feedback ------------------------------------------------------------------------
    async def add_feedback(
        self,
        check_id: uuid.UUID,
        ordinal: int,
        system_verdict: str,
        user_verdict: str,
        comment: str | None,
        citation_raw: str,
    ) -> Feedback:
        row = Feedback(
            check_id=check_id,
            ordinal=ordinal,
            system_verdict=system_verdict,
            user_verdict=user_verdict,
            comment=comment,
            citation_raw=citation_raw,
        )
        async with self.sm() as s:
            s.add(row)
            await s.commit()
        return row
