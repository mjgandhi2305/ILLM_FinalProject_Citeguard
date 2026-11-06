"""Executes one persisted check: shared by the inline job backend and the ARQ worker."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import structlog

from citeguard.db.repo import Repository
from citeguard.domain.models import CheckOptions, CitationResult, InputKind
from citeguard.engine import Engine
from citeguard.observability.metrics import CHECKS_TOTAL, VERDICTS_TOTAL
from citeguard.worker.events import EventBus

log = structlog.get_logger(__name__)


def citation_summary(r: CitationResult) -> dict[str, Any]:
    """Compact per-citation payload for lists and live events."""
    return {
        "index": r.index,
        "verdict": r.verdict.value,
        "confidence": r.confidence,
        "risk_score": r.risk_score,
        "title": r.reference.title,
        "raw": r.reference.raw,
        "headline": r.explanation.headline if r.explanation else None,
        "explanation_mode": r.explanation.mode if r.explanation else None,
        "flags": [f.value for f in r.flags],
        "enriched": r.enriched,
        "has_correction": any(s.kind == "correction" for s in r.suggestions),
        "alternatives": sum(1 for s in r.suggestions if s.kind == "alternative"),
        "claim_support": worst_claim_label(r),
    }


_CLAIM_SEVERITY = ["NOT_SUPPORTED", "PARTIAL", "CANNOT_DETERMINE", "SUPPORTS"]


def worst_claim_label(r: CitationResult) -> str | None:
    labels = {c.label.value for c in r.claim_checks}
    return next((label for label in _CLAIM_SEVERITY if label in labels), None)


async def execute_check(
    check_id: uuid.UUID, *, engine: Engine, repo: Repository, bus: EventBus
) -> None:
    cid = str(check_id)
    check = await repo.get_check(check_id, with_rows=False)
    content = await repo.load_input(check_id)
    if check is None or content is None:
        log.warning("check.missing", check_id=cid)
        return
    await repo.mark_running(check_id)
    await bus.publish(cid, "check.started", {"check_id": cid})
    write_lock = asyncio.Lock()  # serialize DB writes from concurrent citations

    async def on_event(event: str, payload: dict[str, Any]) -> None:
        if event == "check.parsed":
            await repo.set_total(check_id, payload["count"])
            await bus.publish(cid, "check.parsed", {"total": payload["count"]})
        elif event in ("citation.verified", "citation.enriched"):
            result: CitationResult = payload["citation"]
            async with write_lock:
                done = await repo.save_citation(check_id, result)
            await bus.publish(
                cid, event, {"citation": citation_summary(result), "progress_done": done}
            )

    try:
        options = CheckOptions.model_validate(check.options or {})
        kind: InputKind = check.input_kind  # type: ignore[assignment]
        data: str | bytes = (
            content if kind in ("pdf", "docx") else content.decode("utf-8", "replace")
        )
        report = await engine.check(kind, data, options=options, on_event=on_event)
        async with write_lock:
            for r in report.citations:  # final state (enrichment flags etc.)
                await repo.save_citation(check_id, r)
            summary = report.summary.model_dump(mode="json")
            await repo.complete(check_id, summary, report.warnings)
        for r in report.citations:
            VERDICTS_TOTAL.labels(verdict=r.verdict.value).inc()
        CHECKS_TOTAL.labels(status="completed").inc()
        await bus.publish(cid, "check.completed", {"summary": summary, "warnings": report.warnings})
    except Exception as exc:
        log.exception("check.failed", check_id=cid)
        await repo.fail(check_id, f"{type(exc).__name__}: {exc}")
        CHECKS_TOTAL.labels(status="failed").inc()
        await bus.publish(cid, "check.failed", {"error": "The check failed; see server logs."})
