"""Evaluation metrics and the Markdown results report."""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from citeguard.domain.models import Verdict

FAKE = {Verdict.FABRICATED, Verdict.MISATTRIBUTED}
REAL = {Verdict.VERIFIED, Verdict.VERIFIED_WITH_ERRORS}
ORDER = [
    Verdict.VERIFIED,
    Verdict.VERIFIED_WITH_ERRORS,
    Verdict.MISATTRIBUTED,
    Verdict.FABRICATED,
    Verdict.UNVERIFIABLE,
]


@dataclass
class Prediction:
    id: str
    gold: Verdict
    pred: Verdict
    confidence: float
    split: str
    perturbation: str | None = None
    latency_ms: int = 0
    llm_tokens: int = 0
    explanation_mode: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _safe(a: float, b: float) -> float:
    return a / b if b else 0.0


def binary_fake_metrics(preds: list[Prediction]) -> dict[str, float]:
    """Positive class = citation is fake (fabricated or misattributed)."""
    tp = sum(1 for p in preds if p.gold in FAKE and p.pred in FAKE)
    fp = sum(1 for p in preds if p.gold not in FAKE and p.pred in FAKE)
    fn = sum(1 for p in preds if p.gold in FAKE and p.pred not in FAKE)
    real = [p for p in preds if p.gold in REAL]
    precision, recall = _safe(tp, tp + fp), _safe(tp, tp + fn)
    return {
        "precision": precision,
        "recall": recall,
        "f1": _safe(2 * precision * recall, precision + recall),
        # The number that matters most to users: real citations wrongly called fake.
        "false_positive_rate_on_real": _safe(sum(1 for p in real if p.pred in FAKE), len(real)),
        "real_flagged_unverifiable": _safe(
            sum(1 for p in real if p.pred == Verdict.UNVERIFIABLE), len(real)
        ),
    }


def confusion(preds: list[Prediction]) -> dict[str, dict[str, int]]:
    m: dict[str, dict[str, int]] = {g.value: {p.value: 0 for p in ORDER} for g in ORDER}
    for p in preds:
        m[p.gold.value][p.pred.value] += 1
    return m


def macro_f1(preds: list[Prediction]) -> float:
    scores = []
    for v in ORDER:
        tp = sum(1 for p in preds if p.gold == v and p.pred == v)
        fp = sum(1 for p in preds if p.gold != v and p.pred == v)
        fn = sum(1 for p in preds if p.gold == v and p.pred != v)
        if tp + fn == 0:  # average over classes present in the gold labels
            continue
        pr, rc = _safe(tp, tp + fp), _safe(tp, tp + fn)
        scores.append(_safe(2 * pr * rc, pr + rc))
    return statistics.fmean(scores) if scores else 0.0


def expected_calibration_error(preds: list[Prediction], bins: int = 10) -> float:
    buckets: dict[int, list[Prediction]] = defaultdict(list)
    for p in preds:
        buckets[min(bins - 1, int(p.confidence * bins))].append(p)
    total = len(preds)
    ece = 0.0
    for items in buckets.values():
        acc = sum(1 for p in items if p.pred == p.gold) / len(items)
        conf = statistics.fmean(p.confidence for p in items)
        ece += len(items) / total * abs(acc - conf)
    return ece


def by_group(preds: list[Prediction], key: str) -> dict[str, dict[str, float]]:
    groups: dict[str, list[Prediction]] = defaultdict(list)
    for p in preds:
        groups[str(getattr(p, key) or "none")].append(p)
    return {
        g: {
            "n": len(items),
            "accuracy": sum(1 for p in items if p.pred == p.gold) / len(items),
            "fake_detected": sum(1 for p in items if p.pred in FAKE) / len(items),
        }
        for g, items in sorted(groups.items())
    }


def _explanation_pass_rate(preds: list[Prediction]) -> float | None:
    explained = [p for p in preds if p.pred != Verdict.VERIFIED and p.explanation_mode]
    if not explained or not any(p.explanation_mode == "llm" for p in preds):
        return None
    return sum(1 for p in explained if p.explanation_mode == "llm") / len(explained)


def summarize(preds: list[Prediction]) -> dict[str, Any]:
    latencies = sorted(p.latency_ms for p in preds) or [0]
    return {
        "n": len(preds),
        "accuracy": _safe(sum(1 for p in preds if p.pred == p.gold), len(preds)),
        "macro_f1": macro_f1(preds),
        "fake_detection": binary_fake_metrics(preds),
        "ece": expected_calibration_error(preds) if preds else 0.0,
        "confusion": confusion(preds),
        "by_perturbation": by_group(preds, "perturbation"),
        "by_split": by_group(preds, "split"),
        "latency_ms": {
            "p50": latencies[len(latencies) // 2],
            "p95": latencies[min(len(latencies) - 1, int(0.95 * len(latencies)))],
        },
        "llm_tokens_per_citation": _safe(sum(p.llm_tokens for p in preds), len(preds)),
        # share of non-verified citations whose LLM explanation passed the grounding validator
        "llm_explanation_pass_rate": _explanation_pass_rate(preds),
        "gold_distribution": dict(Counter(p.gold.value for p in preds)),
    }


def markdown_report(name: str, s: dict[str, Any]) -> str:
    f = s["fake_detection"]
    lines = [
        f"# CiteBench results: {name}",
        "",
        f"Items: **{s['n']}** · accuracy **{s['accuracy']:.3f}** · macro-F1 **{s['macro_f1']:.3f}** "
        f"· ECE {s['ece']:.3f}",
        "",
        "## Fake-citation detection (fabricated ∪ misattributed)",
        "",
        "| Precision | Recall | F1 | FPR on real citations | Real → unverifiable |",
        "| --- | --- | --- | --- | --- |",
        f"| {f['precision']:.3f} | {f['recall']:.3f} | {f['f1']:.3f} | "
        f"{f['false_positive_rate_on_real']:.3f} | {f['real_flagged_unverifiable']:.3f} |",
        "",
        "## Confusion matrix (rows = gold, columns = predicted)",
        "",
        "| gold \\ pred | " + " | ".join(v.value for v in ORDER) + " |",
        "| --- | " + " | ".join("---" for _ in ORDER) + " |",
    ]
    for g in ORDER:
        row = s["confusion"][g.value]
        if sum(row.values()):
            lines.append(f"| {g.value} | " + " | ".join(str(row[p.value]) for p in ORDER) + " |")
    lines += ["", "## By perturbation", "", "| Perturbation | n | Accuracy | Flagged as fake |",
              "| --- | --- | --- | --- |"]  # fmt: skip
    for k, v in s["by_perturbation"].items():
        lines.append(f"| {k} | {v['n']} | {v['accuracy']:.3f} | {v['fake_detected']:.3f} |")
    lines += [
        "",
        f"Latency p50 {s['latency_ms']['p50']} ms · p95 {s['latency_ms']['p95']} ms · "
        f"LLM tokens per citation {s['llm_tokens_per_citation']:.0f}"
        + (
            f" · LLM explanations passing grounding check {s['llm_explanation_pass_rate']:.0%}"
            if s.get("llm_explanation_pass_rate") is not None
            else ""
        ),
        "",
    ]
    return "\n".join(lines)
