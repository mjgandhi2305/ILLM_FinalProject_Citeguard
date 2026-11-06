"""API end-to-end (in-process): SQLite + inline jobs + in-memory scholarly sources."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from citeguard.api.app import create_app
from citeguard.api.state import AppState
from citeguard.config import Settings
from citeguard.sources.infra import NullCache
from citeguard.sources.registry import SourceSet

ADMIN = "admin-secret-key"
BIB = """@article{lecun, title={Deep learning}, author={LeCun, Yann and Bengio, Yoshua and Hinton, Geoffrey},
  journal={Nature}, year={2018}, volume={520}}
@article{fake, title={Holographic sparse attention for tidal energy forecasting},
  author={Nobody, Ann and Someone, Bob}, journal={Energy Letters}, year={2022}}
@inproceedings{att, title={Attention is all you need}, author={Vaswani, Ashish and Shazeer, Noam},
  booktitle={NeurIPS}, year={2017}}"""


@pytest.fixture
async def app(tmp_path: Path, make_sources: Callable[..., SourceSet]) -> AsyncIterator[FastAPI]:
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/api.db",
        auth_enabled=True,
        admin_api_key=ADMIN,  # type: ignore[arg-type]
        cache_backend="none",
        llm_enabled=False,
        groq_api_key=None,
        max_upload_mb=1,
        suggest_alternatives=False,
    )
    application = create_app(settings, sources=make_sources(), cache=NullCache())
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers={"X-API-Key": ADMIN}
    ) as c:
        yield c


async def wait_done(
    client: httpx.AsyncClient, check_id: str, limit_s: float = 10
) -> dict[str, Any]:
    for _ in range(int(limit_s / 0.05)):
        body = (await client.get(f"/api/v1/checks/{check_id}")).json()
        if body["status"] in ("completed", "failed"):
            return body  # type: ignore[no-any-return]
        await asyncio.sleep(0.05)
    raise AssertionError("check did not finish")


async def test_auth_required(app: FastAPI) -> None:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/api/v1/checks")).status_code == 401
        r = await c.get("/api/v1/checks", headers={"Authorization": "Bearer nope"})
        assert r.status_code == 401
        assert (await c.get("/healthz")).status_code == 200


async def test_bibtex_check_lifecycle_and_exports(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/api/v1/checks", json={"bibtex": BIB, "options": {"suggest_alternatives": False}}
    )
    assert r.status_code == 202
    check_id = r.json()["id"]
    body = await wait_done(client, check_id)
    assert body["status"] == "completed"
    verdicts = [c["verdict"] for c in body["citations"]]
    assert verdicts == ["VERIFIED_WITH_ERRORS", "FABRICATED", "VERIFIED"]
    assert body["summary"]["by_verdict"]["FABRICATED"] == 1
    assert body["progress_done"] == body["progress_total"] == 3

    detail = (await client.get(f"/api/v1/checks/{check_id}/citations/0")).json()
    assert detail["evidence"] and detail["suggestions"][0]["kind"] == "correction"

    bib = await client.get(f"/api/v1/checks/{check_id}/export", params={"format": "bib"})
    assert bib.status_code == 200
    assert "% REMOVED [FABRICATED]" in bib.text
    assert "@article{lecun," in bib.text and "2015" in bib.text  # corrected, key preserved
    html = await client.get(f"/api/v1/checks/{check_id}/export", params={"format": "html"})
    assert "Likely fabricated" in html.text and html.headers["content-type"].startswith("text/html")
    assert "script-src" not in html.headers["content-security-policy"]  # no scripts at all
    assert html.headers["content-security-policy"].startswith("default-src 'none'")
    csv = await client.get(f"/api/v1/checks/{check_id}/export", params={"format": "csv"})
    assert csv.text.count("\n") == 4
    md = await client.get(f"/api/v1/checks/{check_id}/export", params={"format": "md"})
    assert md.text.startswith("# Citation check")


async def test_sse_stream_replays_snapshot_and_completion(client: httpx.AsyncClient) -> None:
    r = await client.post("/api/v1/checks", json={"bibtex": BIB})
    check_id = r.json()["id"]
    await wait_done(client, check_id)
    stream = await client.get(f"/api/v1/checks/{check_id}/events")
    assert stream.status_code == 200
    events = [line[7:] for line in stream.text.splitlines() if line.startswith("event: ")]
    assert events[0] == "snapshot"
    data = next(line[6:] for line in stream.text.splitlines() if line.startswith("data: "))
    assert json.loads(data)["status"] == "completed"


async def test_sync_single_citation(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/api/v1/checks",
        params={"sync": "true"},
        json={"citation": "Vaswani, A., & Shazeer, N. (2017). Attention is all you need. NeurIPS."},
    )
    assert r.status_code == 200
    assert r.json()["verdict"] == "VERIFIED"
    bad = await client.post("/api/v1/checks", params={"sync": "true"}, json={"text": "x"})
    assert bad.status_code == 400


async def test_upload_validation(client: httpx.AsyncClient) -> None:
    ok = await client.post(
        "/api/v1/checks/upload", files={"file": ("refs.bib", BIB.encode(), "text/plain")}
    )
    assert ok.status_code == 202
    await wait_done(client, ok.json()["id"])
    binary = await client.post(
        "/api/v1/checks/upload",
        files={"file": ("x.bin", b"\x00\xff\xfe" * 10, "application/octet-stream")},
    )
    assert binary.status_code == 415
    big = await client.post(
        "/api/v1/checks/upload",
        files={"file": ("big.txt", b"a" * (1024 * 1024 + 10), "text/plain")},
    )
    assert big.status_code == 413
    invalid = await client.post("/api/v1/checks", json={"text": "a", "bibtex": "b"})
    assert invalid.status_code == 422
    # options.claim belongs to single citations; documents carry their own citing sentences
    claim_on_bib = await client.post(
        "/api/v1/checks", json={"bibtex": BIB, "options": {"claim": "Deep nets work."}}
    )
    assert claim_on_bib.status_code == 422
    claim_on_upload = await client.post(
        "/api/v1/checks/upload",
        files={"file": ("refs.bib", BIB.encode(), "text/plain")},
        data={"options": '{"claim": "Deep nets work."}'},
    )
    assert claim_on_upload.status_code == 422
    # a hostile filename cannot break the Content-Disposition header
    odd = await client.post(
        "/api/v1/checks/upload",
        files={"file": ('a"; x=y\r\n.bib', BIB.encode(), "text/plain")},
    )
    assert odd.status_code == 202
    await wait_done(client, odd.json()["id"])
    exp = await client.get(f"/api/v1/checks/{odd.json()['id']}/export", params={"format": "bib"})
    assert re.fullmatch(
        r'attachment; filename="[A-Za-z0-9._-]+-checked\.bib"', exp.headers["content-disposition"]
    )


async def test_key_isolation_feedback_delete_and_rate_limit(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    state: AppState = app.state.cg
    _, key_a = await state.repo.create_api_key("alice", rate_limit_per_min=2)
    _, key_b = await state.repo.create_api_key("bob")
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(
            transport=transport, base_url="http://t", headers={"X-API-Key": key_a}
        ) as a,
        httpx.AsyncClient(
            transport=transport, base_url="http://t", headers={"X-API-Key": key_b}
        ) as b,
    ):
        created = await a.post("/api/v1/checks", json={"bibtex": BIB})
        check_id = created.json()["id"]
        await wait_done(a, check_id)
        assert (await b.get(f"/api/v1/checks/{check_id}")).status_code == 404
        assert [c["id"] for c in (await b.get("/api/v1/checks")).json()] == []

        fb = await a.post(
            f"/api/v1/checks/{check_id}/citations/1/feedback",
            json={"user_verdict": "VERIFIED", "comment": "this is my own unpublished paper"},
        )
        assert fb.status_code == 201

        assert (await a.post("/api/v1/checks", json={"citation": "x y z"})).status_code == 202
        limited = await a.post("/api/v1/checks", json={"citation": "x y z"})
        assert limited.status_code == 429 and "retry-after" in limited.headers

        assert (await a.delete(f"/api/v1/checks/{check_id}")).status_code == 204
        assert (await a.get(f"/api/v1/checks/{check_id}")).status_code == 404


async def test_ops_endpoints(client: httpx.AsyncClient) -> None:
    assert (await client.get("/readyz")).status_code == 200
    metrics = await client.get("/metrics")
    assert "citeguard_checks_total" in metrics.text
    health = (await client.get("/api/v1/sources/health")).json()
    assert set(health["sources"]) >= {"crossref", "openalex"}
    assert health["llm"]["enabled"] is False


async def test_interrupted_checks_are_requeued_on_restart(
    tmp_path: Path, make_sources: Callable[..., SourceSet]
) -> None:
    from citeguard.db.repo import Repository
    from citeguard.db.session import create_all, make_engine, make_sessionmaker

    url = f"sqlite+aiosqlite:///{tmp_path}/restart.db"
    db = make_engine(url)
    await create_all(db)
    repo = Repository(make_sessionmaker(db))
    stale = await repo.create_check(
        input_kind="bibtex",
        content=BIB.encode(),
        options={},
        filename=None,
        owner_key_id=None,
        retention_days=1,
        pipeline_version="t",
    )
    await repo.mark_running(stale.id)  # simulates a crash mid-check
    await db.dispose()

    settings = Settings(
        database_url=url,
        auth_enabled=False,
        cache_backend="none",
        llm_enabled=False,
        groq_api_key=None,
    )
    application = create_app(settings, sources=make_sources(), cache=NullCache())
    async with (
        application.router.lifespan_context(application),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://t") as c,
    ):
        body = await wait_done(c, str(stale.id))
    assert body["status"] == "completed" and len(body["citations"]) == 3
