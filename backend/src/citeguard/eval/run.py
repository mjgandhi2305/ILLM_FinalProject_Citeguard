"""Run CiteGuard (or a baseline) over a CiteBench file and report metrics.

    python -m citeguard.eval.run --dataset ../eval/datasets/citebench_dev.jsonl --mode no_llm

Modes (the ablation ladder of the design doc):
    heuristics   offline screening signals only (no network, no LLM)
    exact        retrieval + exact identifier / exact title matching only
    no_llm       full deterministic pipeline (fuzzy linkage, rules, templates)
    full         full pipeline with Groq (parsing, adjudication, reformulation, explanations)
    llm_only     baseline: ask the LLM "is this citation real?" with no retrieval

Predictions are appended as they finish, so an interrupted run resumes where it stopped."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from citeguard.config import get_settings
from citeguard.domain.models import CheckOptions, CitationResult, Verdict
from citeguard.engine import Engine, make_cache
from citeguard.eval.dataset import BenchItem, load
from citeguard.eval.metrics import Prediction, markdown_report, summarize
from citeguard.ingest.bibtex import parse_bibtex
from citeguard.match.normalize import normalize_title
from citeguard.observability.logging import configure_logging
from citeguard.parse.heuristic import parse_heuristic
from citeguard.parse.identifiers import normalize_doi
from citeguard.screen.heuristics import screen

Mode = Literal["heuristics", "exact", "no_llm", "full", "llm_only"]
RUNS_DIR = Path(__file__).resolve().parents[4] / "eval" / "runs"


def _candidate_rows(item: BenchItem, r: CitationResult) -> list[dict[str, Any]]:
    """Linkage training rows: candidate features + whether it is the item's true source."""
    if not (item.source_doi or item.source_title):
        return []
    rows = []
    for c in r.candidates:
        same = bool(
            (item.source_doi and normalize_doi(c.record.doi) == normalize_doi(item.source_doi))
            or (
                item.source_title
                and normalize_title(c.record.title) == normalize_title(item.source_title)
            )
        )
        rows.append({"features": c.features.model_dump(), "same": same})
    return rows


def _prediction(item: BenchItem, r: CitationResult | None, latency_ms: int) -> dict[str, Any]:
    if r is None:
        return Prediction(
            id=item.id,
            gold=item.label,
            pred=Verdict.UNVERIFIABLE,
            confidence=0.0,
            split=item.split,
            perturbation=item.perturbation,
            latency_ms=latency_ms,
        ).__dict__ | {"extra": {"note": "no citation parsed"}}
    return Prediction(
        id=item.id,
        gold=item.label,
        pred=r.verdict,
        confidence=r.confidence,
        split=item.split,
        perturbation=item.perturbation,
        latency_ms=latency_ms,
        llm_tokens=r.llm_usage.input_tokens + r.llm_usage.output_tokens,
        explanation_mode=r.explanation.mode if r.explanation else None,
        extra={
            "codes": [d.code.value for d in r.discrepancies],
            "flags": [f.value for f in r.flags],
            "linkage": _candidate_rows(item, r),
        },
    ).__dict__


async def _heuristic_prediction(item: BenchItem) -> dict[str, Any]:
    started = time.perf_counter()
    if item.input_kind == "bibtex":
        refs, _ = parse_bibtex(item.text)
        ref = refs[0] if refs else parse_heuristic(item.text)
    else:
        ref = parse_heuristic(item.text)
    risk, _ = screen(ref)
    pred = Verdict.FABRICATED if risk >= 0.3 else Verdict.VERIFIED
    return Prediction(
        id=item.id,
        gold=item.label,
        pred=pred,
        confidence=max(risk, 1 - risk),
        split=item.split,
        perturbation=item.perturbation,
        latency_ms=int((time.perf_counter() - started) * 1000),
    ).__dict__


class _Judgement(BaseModel):
    exists: Literal["yes", "no", "unsure"]
    confidence: float
    reason: str


async def _llm_only_predictions(items: list[BenchItem], out: Path) -> None:
    from citeguard.llm.client import StageConfig
    from citeguard.llm.services import build_llm_services

    settings = get_settings()
    if not settings.llm_available:
        raise SystemExit("llm_only needs GROQ_API_KEY")
    services = build_llm_services(settings, cache=make_cache(settings))
    llm = services.explainer.llm  # type: ignore[union-attr]
    stage = StageConfig(settings.llm_model_explain, "medium", 1500)
    system = (
        "Decide whether the cited publication really exists exactly as cited, using only "
        "your own knowledge. Answer exists = yes, no, or unsure."
    )
    for item in items:
        started = time.perf_counter()
        out_j, usage = await llm.structured(stage, system, f"<data>{item.text}</data>", _Judgement)
        pred = {"yes": Verdict.VERIFIED, "no": Verdict.FABRICATED}.get(
            out_j.exists if out_j else "unsure", Verdict.UNVERIFIABLE
        )
        row = Prediction(
            id=item.id,
            gold=item.label,
            pred=pred,
            confidence=max(0.0, min(1.0, out_j.confidence)) if out_j else 0.0,
            split=item.split,
            perturbation=item.perturbation,
            latency_ms=int((time.perf_counter() - started) * 1000),
            llm_tokens=usage.input_tokens + usage.output_tokens,
        ).__dict__
        _append(out, row)


def _append(path: Path, row: dict[str, Any]) -> None:
    with path.open("a") as fh:
        fh.write(json.dumps(row, default=str) + "\n")


async def run(
    dataset: Path, mode: Mode, limit: int | None, concurrency: int, name: str, explain: bool = False
) -> Path:
    items = load(dataset)[: limit or None]
    out_dir = RUNS_DIR / name
    out_dir.mkdir(parents=True, exist_ok=True)
    pred_path = out_dir / "predictions.jsonl"
    done = (
        {json.loads(line)["id"] for line in pred_path.read_text().splitlines() if line.strip()}
        if pred_path.exists()
        else set()
    )
    todo = [it for it in items if it.id not in done]
    print(f"{name}: {len(todo)} to run ({len(done)} already done)")

    if mode == "heuristics":
        for it in todo:
            _append(pred_path, await _heuristic_prediction(it))
    elif mode == "llm_only":
        await _llm_only_predictions(todo, pred_path)
    else:
        settings = get_settings()
        options = CheckOptions(
            use_llm=mode == "full", explain=explain, suggest_alternatives=False, styles=["apa"]
        )
        verifier_options = {"exact_titles": True, "chimera_check": False} if mode == "exact" else {}
        async with Engine(settings, verifier_options=verifier_options) as engine:
            sem = asyncio.Semaphore(concurrency)
            finished = 0

            async def one(it: BenchItem) -> None:
                nonlocal finished
                async with sem:
                    started = time.perf_counter()
                    try:
                        report = await engine.check(it.input_kind, it.text, options=options)
                        r = report.citations[0] if report.citations else None
                    except Exception as exc:  # record and continue
                        print(f"  {it.id}: error {exc}")
                        r = None
                    _append(
                        pred_path, _prediction(it, r, int((time.perf_counter() - started) * 1000))
                    )
                    finished += 1
                    if finished % 10 == 0:
                        print(f"  {finished}/{len(todo)}")

            await asyncio.gather(*(one(it) for it in todo))

    rows = [json.loads(line) for line in pred_path.read_text().splitlines() if line.strip()]
    keep = {it.id for it in items}
    preds = [
        Prediction(**{k: v for k, v in row.items() if k in Prediction.__dataclass_fields__})
        for row in rows
        if row["id"] in keep
    ]
    for p in preds:
        p.gold, p.pred = Verdict(p.gold), Verdict(p.pred)
    summary = summarize(preds)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    report = markdown_report(f"{name} ({mode})", summary)
    (out_dir / "report.md").write_text(report)
    print(report)
    return out_dir


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--dataset", type=Path, required=True)
    ap.add_argument(
        "--mode", choices=["heuristics", "exact", "no_llm", "full", "llm_only"], default="no_llm"
    )
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--name", default=None, help="run name (default: <dataset>-<mode>)")
    ap.add_argument(
        "--explain", action="store_true", help="full mode: also generate LLM explanations"
    )
    args = ap.parse_args()
    configure_logging("WARNING")
    name = args.name or f"{args.dataset.stem}-{args.mode}"
    asyncio.run(run(args.dataset, args.mode, args.limit, args.concurrency, name, args.explain))


if __name__ == "__main__":
    main()
