"""Claim-support check evaluation on real CiteBench papers.

For each real paper with an abstract, two claims are judged against that abstract:
  supported    the paper's own concluding sentence, lightly rephrased (lead-ins such as
               "We show that" removed). NOT_SUPPORTED here is a false alarm.
  unsupported  the concluding sentence of a different, random paper. Expected NOT_SUPPORTED.

Synthetic claims measure false alarms and gross mismatches, not subtle misuse (a claim that
overgeneralises a real finding); that needs a hand-labelled set.

    python -m citeguard.eval.claims --dataset ../eval/datasets/citebench_test2.jsonl --n 25
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from citeguard.config import get_settings
from citeguard.domain.models import CheckOptions, ClaimSupport, Verdict
from citeguard.engine import Engine
from citeguard.eval.dataset import load
from citeguard.observability.logging import configure_logging
from citeguard.verify.claims import find_abstract

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
# Abstract tails that are not claims anyone would cite
_BOILERPLATE_RE = re.compile(
    r"trial registration|registry|keywords?\s*:|bibliography|©|copyright|all rights reserved|"
    r"funding|conflicts? of interest|\b\d\)|"
    r"(?:further|future) (?:research|studies|work|investigation)",
    re.IGNORECASE,
)
_LEAD_IN_RE = re.compile(
    r"^(?:in conclusion|in summary|overall|taken together|"
    r"(?:these|our) (?:results|findings|data)(?: further| also)? "
    r"(?:suggest|indicate|show|demonstrate|confirm|reveal)|"
    r"we (?:show|found|find|conclude|demonstrate|observed)|"
    r"this (?:study|paper|work|review) (?:shows|demonstrates|suggests|indicates|found))"
    r"(?: that)?[,:]?\s*",
    re.IGNORECASE,
)


def conclusion_claim(abstract: str) -> str | None:
    """The last substantive sentence of the abstract (not registration, keywords or future
    work), as a manuscript would cite it."""
    sentences = [
        s.strip()
        for s in _SENTENCE_RE.split(abstract)
        if len(s.split()) >= 8 and not _BOILERPLATE_RE.search(s)
    ]
    if not sentences:
        return None
    s = _LEAD_IN_RE.sub("", sentences[-1]).rstrip(" .")
    return s[:1].upper() + s[1:] + " [1]."


async def collect(dataset: Path, n: int) -> list[dict[str, Any]]:
    settings = get_settings()
    if not settings.llm_available:
        raise SystemExit("needs GROQ_API_KEY")
    items = [i for i in load(dataset) if i.label == Verdict.VERIFIED][: n * 3]
    papers: list[tuple[str, Any, str, str]] = []  # (id, record, abstract, own claim)
    async with Engine(settings) as engine:
        assert engine.sources is not None and engine.llm is not None
        checker = engine.llm.claim_checker
        assert checker is not None
        options = CheckOptions(use_llm=False, explain=False, suggest_alternatives=False)
        for item in items:
            if len(papers) >= n:
                break
            report = await engine.check(item.input_kind, item.text, options=options)
            if not report.citations or report.citations[0].verdict != Verdict.VERIFIED:
                continue
            found = await find_abstract(engine.sources, report.citations[0])
            claim = conclusion_claim(found[0]) if found else None
            if found and claim:
                papers.append((item.id, report.citations[0].best_match.record, found[0], claim))  # type: ignore[union-attr]

        rows = []
        for i, (pid, rec, abstract, own) in enumerate(papers):
            other = papers[(i + len(papers) // 2) % len(papers)][3]
            for kind, claim in (("supported", own), ("unsupported", other)):
                checks, usage = await checker.check(rec, abstract, [claim])
                c = checks[0] if checks else None
                rows.append(
                    {
                        "id": pid,
                        "kind": kind,
                        "claim": claim,
                        "label": c.label.value if c else None,
                        "grounded": bool(c and c.mode == "llm"),
                        "rationale": c.rationale if c else None,
                        "tokens": usage.input_tokens + usage.output_tokens,
                    }
                )
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def share(kind: str, labels: set[str]) -> float:
        group = [r for r in rows if r["kind"] == kind]
        return (
            round(sum(1 for r in group if r["label"] in labels) / len(group), 3) if group else 0.0
        )

    not_sup = {ClaimSupport.NOT_SUPPORTED.value}
    return {
        "papers": len(rows) // 2,
        "supported": dict(Counter(r["label"] for r in rows if r["kind"] == "supported")),
        "unsupported": dict(Counter(r["label"] for r in rows if r["kind"] == "unsupported")),
        "false_alarm_rate": share("supported", not_sup),
        "support_rate": share("supported", {"SUPPORTS", "PARTIAL"}),
        "detection_rate": share("unsupported", not_sup),
        # judgements dropped because their quote was not in the abstract (or the call failed)
        "ungrounded": sum(1 for r in rows if not r["grounded"]),
        "tokens_per_check": round(sum(r["tokens"] for r in rows) / max(1, len(rows))),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--dataset", type=Path, required=True)
    ap.add_argument("--n", type=int, default=25, help="papers (two claims each)")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    configure_logging("WARNING")
    out = args.out or Path("../eval/runs") / f"claims-{args.dataset.stem}"
    rows = asyncio.run(collect(args.dataset, args.n))
    out.mkdir(parents=True, exist_ok=True)
    (out / "predictions.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    summary = summarize(rows)
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
