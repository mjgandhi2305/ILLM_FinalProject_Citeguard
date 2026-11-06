"""REST + SSE routes (`/api/v1`)."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import ValidationError
from sse_starlette.sse import EventSourceResponse

from citeguard.api.auth import CurrentPrincipal, RateLimitedPrincipal
from citeguard.api.schemas import (
    CheckCreate,
    CheckCreated,
    CheckListItem,
    CheckOut,
    CitationSummary,
    FeedbackIn,
    FeedbackOut,
    SourceHealth,
)
from citeguard.api.state import AppState, get_state
from citeguard.db.models import Check
from citeguard.domain.models import CheckOptions, CitationResult, InputKind
from citeguard.ingest.documents import UnsupportedDocumentError, sniff_kind
from citeguard.report import exporters
from citeguard.worker.events import TERMINAL_EVENTS
from citeguard.worker.runner import citation_summary

router = APIRouter(prefix="/api/v1", tags=["checks"])

ALLOWED_UPLOAD_KINDS: set[str] = {"pdf", "docx", "bibtex", "latex", "text"}


def _links(check_id: uuid.UUID) -> dict[str, str]:
    base = f"/api/v1/checks/{check_id}"
    return {"self": base, "events": f"{base}/events", "export": f"{base}/export"}


def _results(check: Check) -> list[CitationResult]:
    return [CitationResult.model_validate(row.result) for row in check.citations]


def _check_out(check: Check) -> CheckOut:
    return CheckOut(
        id=check.id,
        status=check.status,
        input_kind=check.input_kind,
        filename=check.filename,
        progress_total=check.progress_total,
        progress_done=check.progress_done,
        created_at=check.created_at,
        started_at=check.started_at,
        completed_at=check.completed_at,
        expires_at=check.expires_at,
        summary=check.summary,
        warnings=check.warnings or [],
        error=check.error,
        citations=[CitationSummary(**citation_summary(r)) for r in _results(check)],
    )


async def _load(st: AppState, check_id: uuid.UUID, owner: uuid.UUID | None) -> Check:
    check = await st.repo.get_check(check_id, owner_key_id=owner)
    if check is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Check not found")
    return check


async def _create(
    st: AppState,
    principal: CurrentPrincipal,
    kind: InputKind,
    content: bytes,
    options: CheckOptions,
    filename: str | None,
) -> CheckCreated:
    check = await st.repo.create_check(
        input_kind=kind,
        content=content,
        options=options.model_dump(mode="json"),
        filename=filename,
        owner_key_id=principal.key_id,
        retention_days=st.settings.retention_days,
        pipeline_version=st.settings.app_version,
    )
    await st.enqueue(check.id)
    return CheckCreated(id=check.id, status="queued", links=_links(check.id))


@router.post(
    "/checks",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=CheckCreated,
    summary="Check pasted text, a BibTeX bibliography or a single citation",
    responses={200: {"description": "`sync=true` with a single citation: the full result"}},
)
async def create_check(
    body: CheckCreate,
    request: Request,
    principal: RateLimitedPrincipal,
    sync: Annotated[bool, Query(description="Verify a single citation inline")] = False,
) -> Any:
    st = get_state(request)
    kind, content = body.kind_and_content()
    if sync:
        if kind != "citation":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "sync=true needs `citation` input")
        report = await st.engine.check(kind, content, options=body.options)
        payload = report.citations[0].model_dump(mode="json") if report.citations else None
        return JSONResponse(status_code=200, content=payload)
    return await _create(st, principal, kind, content.encode(), body.options, None)


@router.post(
    "/checks/upload",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=CheckCreated,
    summary="Check an uploaded document (.pdf, .docx, .bib, .tex, .txt, .md)",
)
async def upload_check(
    request: Request,
    principal: RateLimitedPrincipal,
    file: Annotated[UploadFile, File()],
    options: Annotated[str | None, Form(description="CheckOptions as JSON")] = None,
) -> CheckCreated:
    st = get_state(request)
    limit = st.settings.max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, f"File exceeds {st.settings.max_upload_mb} MB"
        )
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty file")
    try:
        kind = sniff_kind(data, file.filename)
    except UnsupportedDocumentError as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc
    if kind not in ALLOWED_UPLOAD_KINDS:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"Unsupported type: {kind}")
    try:
        opts = CheckOptions.model_validate_json(options) if options else CheckOptions()
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.errors()) from exc
    if opts.claim:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "options.claim is for single-citation input; documents carry their own",
        )
    filename = (file.filename or "upload")[-200:]
    return await _create(st, principal, kind, data, opts, filename)  # type: ignore[arg-type]


@router.get("/checks", response_model=list[CheckListItem])
async def list_checks(request: Request, principal: CurrentPrincipal) -> list[CheckListItem]:
    st = get_state(request)
    rows = await st.repo.list_checks(principal.owner_filter)
    return [CheckListItem.model_validate(r, from_attributes=True) for r in rows]


@router.get("/checks/{check_id}", response_model=CheckOut)
async def get_check(check_id: uuid.UUID, request: Request, principal: CurrentPrincipal) -> CheckOut:
    st = get_state(request)
    return _check_out(await _load(st, check_id, principal.owner_filter))


@router.get(
    "/checks/{check_id}/events",
    summary="Server-sent events: snapshot, citation.verified, citation.enriched, check.completed",
)
async def check_events(
    check_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> EventSourceResponse:
    st = get_state(request)
    await _load(st, check_id, principal.owner_filter)  # 404 / ownership check

    async def stream() -> AsyncIterator[dict[str, str]]:
        # Subscribe before taking the snapshot so no event can fall in between.
        async with st.bus.subscribe(str(check_id)) as events:
            check = await _load(st, check_id, principal.owner_filter)
            snapshot = _check_out(check)
            yield {"event": "snapshot", "data": snapshot.model_dump_json()}
            if snapshot.status in ("completed", "failed"):
                return
            async for event, data in events:
                if await request.is_disconnected():
                    return
                yield {"event": event, "data": json.dumps(data, default=str)}
                if event in TERMINAL_EVENTS:
                    return

    return EventSourceResponse(stream(), ping=15)


@router.get("/checks/{check_id}/citations/{index}", response_model=CitationResult)
async def get_citation(
    check_id: uuid.UUID, index: int, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    st = get_state(request)
    check = await _load(st, check_id, principal.owner_filter)
    row = next((r for r in check.citations if r.ordinal == index), None)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Citation not found")
    return row.result


ExportFormat = Literal["json", "csv", "md", "html", "bib"]
_MEDIA = {
    "json": "application/json",
    "csv": "text/csv; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
    "html": "text/html; charset=utf-8",
    "bib": "application/x-bibtex; charset=utf-8",
}


@router.get("/checks/{check_id}/export")
async def export_check(
    check_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    format: Annotated[ExportFormat, Query()] = "json",
    style: Annotated[Literal["apa", "ieee", "bibtex"], Query()] = "apa",
) -> Response:
    st = get_state(request)
    check = await _load(st, check_id, principal.owner_filter)
    results = _results(check)
    meta = {
        "id": str(check.id),
        "filename": check.filename,
        "input_kind": check.input_kind,
        "status": check.status,
        "summary": check.summary,
        "created_at": check.created_at.isoformat(),
    }
    if format == "json":
        body = exporters.to_json(meta, results)
    elif format == "csv":
        body = exporters.to_csv(results)
    elif format == "md":
        body = exporters.to_markdown(meta, results, style)
    elif format == "html":
        body = exporters.to_html(meta, results, style)
    else:
        body = exporters.to_corrected_bibtex(results)
    # The uploaded filename is user input: keep it out of header syntax.
    stem = re.sub(
        r"[^A-Za-z0-9._-]+", "_", (check.filename or "citeguard-report").rsplit(".", 1)[0]
    )
    ext = {"md": "md", "bib": "bib"}.get(format, format)
    disposition = "inline" if format == "html" else "attachment"
    headers = {"Content-Disposition": f'{disposition}; filename="{stem[:80]}-checked.{ext}"'}
    if format == "html":  # a static page: no scripts, no external loads
        headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
        )
    return PlainTextResponse(body, media_type=_MEDIA[format], headers=headers)


@router.post(
    "/checks/{check_id}/citations/{index}/feedback",
    response_model=FeedbackOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_feedback(
    check_id: uuid.UUID,
    index: int,
    body: FeedbackIn,
    request: Request,
    principal: CurrentPrincipal,
) -> FeedbackOut:
    st = get_state(request)
    check = await _load(st, check_id, principal.owner_filter)
    row = next((r for r in check.citations if r.ordinal == index), None)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Citation not found")
    fb = await st.repo.add_feedback(
        check_id,
        index,
        row.verdict,
        body.user_verdict.value,
        body.comment,
        row.result["reference"]["raw"],
    )
    return FeedbackOut(id=fb.id)


@router.delete("/checks/{check_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_check(
    check_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> Response:
    st = get_state(request)
    if not await st.repo.delete_check(check_id, principal.owner_filter):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Check not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/sources/health", response_model=SourceHealth, tags=["ops"])
async def sources_health(request: Request, principal: CurrentPrincipal) -> SourceHealth:
    st = get_state(request)
    llm: dict[str, Any] = {"enabled": st.engine.llm is not None}
    if st.engine.llm is not None and st.engine.llm.explainer is not None:
        limiter = getattr(getattr(st.engine.llm.explainer, "llm", None), "limiter", None)
        if limiter is not None:
            llm["daily_budget_left"] = limiter.budget_left()
            llm["models"] = {m: limiter.remaining_today(m) for m in st.settings.llm_fallback_models}
    return SourceHealth(sources=st.engine.source_health(), llm=llm)
