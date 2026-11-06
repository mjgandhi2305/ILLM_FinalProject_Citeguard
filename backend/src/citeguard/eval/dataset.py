"""CiteBench item format (JSONL, one item per line)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from citeguard.domain.models import Verdict

Split = Literal["real", "perturbed", "llm_hallucinated", "hard_negative"]


class BenchItem(BaseModel):
    id: str
    split: Split
    input_kind: Literal["citation", "bibtex"]
    text: str  # what CiteGuard receives
    label: Verdict
    perturbation: str | None = None  # e.g. "year_shift", "borrowed_doi"
    style: str | None = None  # apa / ieee / vancouver / bibtex
    source: str | None = None  # crossref / openalex / groq:<model>
    source_doi: str | None = None  # DOI of the real work behind the item (if any)
    source_title: str | None = None
    field: str | None = None
    notes: str | None = None


def load(path: Path) -> list[BenchItem]:
    return [
        BenchItem.model_validate_json(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def save(items: list[BenchItem], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(item.model_dump_json(exclude_none=True) + "\n" for item in items))
