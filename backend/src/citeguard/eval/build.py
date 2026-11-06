"""Build CiteBench splits from live Crossref / OpenAlex samples.

    python -m citeguard.eval.build --real 100 --perturbed 150 --fabricated 60 \
        --seed 7 --out ../eval/datasets/citebench_dev.jsonl

Ground truth comes from construction: real records are sampled from two indexes (so the
benchmark does not depend on a single source the system also queries), perturbations have
known labels, and fully fabricated titles are generated from templates."""

from __future__ import annotations

import argparse
import asyncio
import random
from pathlib import Path
from typing import Any, Literal

import httpx

from citeguard.config import get_settings
from citeguard.domain.models import Author, CitationType, Record, Verdict
from citeguard.eval.dataset import BenchItem, save
from citeguard.match.normalize import word_count
from citeguard.sources.csl import csl_to_record
from citeguard.sources.openalex import SELECT, work_to_record
from citeguard.suggest.format import format_apa, format_bibtex, format_ieee

# --------------------------------------------------------------------------------------------
# Sampling
# --------------------------------------------------------------------------------------------


def _usable(r: Record) -> bool:
    return bool(
        r.title
        and 5 <= word_count(r.title) <= 30
        and r.authors
        and r.year
        and 1980 <= r.year <= 2025
        and r.container_title
        and not r.is_retracted
        and r.type in (CitationType.ARTICLE_JOURNAL, CitationType.PAPER_CONFERENCE)
        and not any(
            w in r.title.lower()
            for w in ("erratum", "correction", "editorial", "issue information")
        )
    )


async def sample_openalex(
    client: httpx.AsyncClient, n: int, seed: int, email: str, api_key: str | None = None
) -> list[Record]:
    params: dict[str, Any] = {
        "sample": min(200, n * 2),
        "seed": seed,
        "per-page": min(200, n * 2),
        "filter": "has_doi:true,type:article,language:en,publication_year:1990-2024",
        "select": SELECT,
        "mailto": email,
    }
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    resp = await client.get("https://api.openalex.org/works", params=params, headers=headers)
    resp.raise_for_status()
    records = [work_to_record(w) for w in resp.json().get("results", [])]
    return [r for r in records if _usable(r)][:n]


async def sample_crossref(client: httpx.AsyncClient, n: int, email: str) -> list[Record]:
    out: list[Record] = []
    for _ in range(6):
        if len(out) >= n:
            break
        resp = await client.get(
            "https://api.crossref.org/works",
            params={
                "sample": 100,
                "filter": "type:journal-article,from-pub-date:1990,until-pub-date:2024",
                "mailto": email,
            },
        )
        resp.raise_for_status()
        for item in resp.json()["message"]["items"]:
            rec = csl_to_record(item, source="crossref")
            if _usable(rec):
                out.append(rec)
    return out[:n]


# --------------------------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------------------------


def format_vancouver(r: Record) -> str:
    names = []
    for a in r.authors[:6]:
        initials = "".join(p[0] for p in (a.given or "").replace("-", " ").split() if p)
        names.append(f"{a.family} {initials}".strip())
    authors = ", ".join(names) + (", et al" if len(r.authors) > 6 else "")
    tail = f"{r.year}"
    if r.volume:
        tail += f";{r.volume}"
        if r.issue:
            tail += f"({r.issue})"
    if r.pages:
        tail += f":{r.pages}"
    return f"{authors}. {r.title}. {r.container_title}. {tail}."


STYLES = ("apa", "ieee", "vancouver", "bibtex")


def render(
    r: Record, rng: random.Random, keep_doi: bool
) -> tuple[str, Literal["citation", "bibtex"], str]:
    """Returns (text, input_kind, style)."""
    rec = r.model_copy(update={"url": None, **({} if keep_doi else {"doi": None})})
    style = rng.choice(STYLES)
    if style == "apa":
        return format_apa(rec), "citation", style
    if style == "ieee":
        return format_ieee(rec), "citation", style
    if style == "vancouver":
        text = format_vancouver(rec)
        return (text + (f" doi:{rec.doi}" if rec.doi else "")), "citation", style
    return format_bibtex(rec), "bibtex", style


# --------------------------------------------------------------------------------------------
# Perturbations (each with its ground-truth label)
# --------------------------------------------------------------------------------------------

ADJ = ["Scalable", "Robust", "Contrastive", "Hierarchical", "Adaptive", "Federated", "Causal",
       "Self-Supervised", "Multi-Scale", "Interpretable", "Probabilistic", "Graph-Based",
       "Sparse", "Bayesian", "Explainable", "Physics-Informed"]  # fmt: skip
METHOD = ["Transformers", "Diffusion Models", "Attention Networks", "Representation Learning",
          "Reinforcement Learning", "Variational Inference", "Neural Operators",
          "Knowledge Distillation", "Metric Learning", "Prompt Tuning", "Ensemble Methods",
          "Mixture-of-Experts Models"]  # fmt: skip
TASK = ["Early Detection of Sepsis", "Protein Folding Dynamics", "Low-Resource Machine Translation",
        "Urban Traffic Forecasting", "Antimicrobial Resistance Prediction", "Wildfire Spread Modelling",
        "Clinical Trial Outcome Prediction", "Crop Yield Estimation", "Fraud Detection",
        "Seismic Event Localization", "Drug–Target Interaction Prediction", "Glacier Melt Forecasting",
        "Mental Health Screening", "Battery Degradation Prediction"]  # fmt: skip
DOMAIN = ["in Electronic Health Records", "from Satellite Imagery", "under Distribution Shift",
          "with Limited Labels", "in Developing Countries", "Across Heterogeneous Hospitals",
          "from Wearable Sensors", "in Smart Grids", ""]  # fmt: skip


def fabricated_title(rng: random.Random) -> str:
    title = f"{rng.choice(ADJ)} {rng.choice(METHOD)} for {rng.choice(TASK)} {rng.choice(DOMAIN)}"
    return title.strip()


def perturb(
    kind: str, r: Record, pool: list[Record], rng: random.Random
) -> tuple[Record, Verdict] | None:
    other = rng.choice([p for p in pool if p.doi != r.doi])
    if kind == "year_shift":
        assert r.year is not None
        return r.model_copy(
            update={"year": r.year + rng.choice([-3, -2, 2, 3])}
        ), Verdict.VERIFIED_WITH_ERRORS
    if kind == "venue_swap":
        if not other.container_title or other.container_title == r.container_title:
            return None
        return r.model_copy(
            update={"container_title": other.container_title}
        ), Verdict.VERIFIED_WITH_ERRORS
    if kind == "bogus_doi":  # real paper, DOI that does not exist
        if not r.doi:
            return None
        bogus = r.doi.split("/", 1)[0] + "/cg." + "".join(rng.choices("0123456789abcdef", k=10))
        return r.model_copy(update={"doi": bogus}), Verdict.VERIFIED_WITH_ERRORS
    if kind == "author_swap":  # real title, someone else's authors
        return r.model_copy(update={"authors": other.authors}), Verdict.MISATTRIBUTED
    if kind == "wrong_doi":  # real paper, DOI of a different real paper
        if not other.doi:
            return None
        return r.model_copy(update={"doi": other.doi}), Verdict.MISATTRIBUTED
    if kind == "fabricated":  # invented title, real-looking authors and venue
        authors = other.authors[:3] or [Author(family="Smith", given="J.")]
        return (
            r.model_copy(
                update={
                    "title": fabricated_title(rng),
                    "authors": authors,
                    "doi": None,
                    "pages": None,
                }
            ),
            Verdict.FABRICATED,
        )
    if kind == "borrowed_doi":  # invented title carrying a real DOI
        return (
            r.model_copy(update={"title": fabricated_title(rng), "doi": other.doi}),
            Verdict.FABRICATED,
        )
    raise ValueError(kind)


PERTURBATIONS = [
    "year_shift",
    "venue_swap",
    "bogus_doi",
    "author_swap",
    "wrong_doi",
    "borrowed_doi",
]


async def build(real: int, perturbed: int, fabricated: int, seed: int) -> list[BenchItem]:
    settings = get_settings()
    rng = random.Random(seed)
    oa_key = settings.openalex_api_key.get_secret_value() if settings.openalex_api_key else None
    async with httpx.AsyncClient(
        timeout=60, headers={"User-Agent": settings.user_agent}, follow_redirects=True
    ) as client:
        oa, cr = await asyncio.gather(
            sample_openalex(client, real, seed, settings.contact_email, oa_key),
            sample_crossref(client, real, settings.contact_email),
        )
    pool = oa + cr
    rng.shuffle(pool)
    items: list[BenchItem] = []

    for i, r in enumerate(pool[:real]):
        text, kind, style = render(r, rng, keep_doi=rng.random() < 0.5)
        items.append(
            BenchItem(
                id=f"real-{i:04d}",
                split="real",
                input_kind=kind,
                text=text,
                label=Verdict.VERIFIED,
                style=style,
                source=r.source,
                source_doi=r.doi,
                source_title=r.title,
            )
        )

    made = 0
    attempts = 0
    while made < perturbed and attempts < perturbed * 5:
        attempts += 1
        r = rng.choice(pool)
        pkind = PERTURBATIONS[made % len(PERTURBATIONS)]
        out = perturb(pkind, r, pool, rng)
        if out is None:
            continue
        rec, label = out
        keep = pkind in ("bogus_doi", "wrong_doi", "borrowed_doi") or rng.random() < 0.5
        text, ikind, style = render(rec, rng, keep_doi=keep)
        items.append(
            BenchItem(
                id=f"pert-{made:04d}",
                split="perturbed",
                input_kind=ikind,
                text=text,
                label=label,
                perturbation=pkind,
                style=style,
                source=r.source,
                source_doi=r.doi,
                source_title=r.title,
            )
        )
        made += 1

    for i in range(fabricated):
        r = rng.choice(pool)
        out = perturb("fabricated", r, pool, rng)
        assert out is not None
        rec, label = out
        text, ikind, style = render(rec, rng, keep_doi=False)
        items.append(
            BenchItem(
                id=f"fab-{i:04d}",
                split="perturbed",
                input_kind=ikind,
                text=text,
                label=label,
                perturbation="fabricated",
                style=style,
                source="template",
            )
        )
    rng.shuffle(items)
    return items


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--real", type=int, default=100)
    ap.add_argument("--perturbed", type=int, default=150)
    ap.add_argument("--fabricated", type=int, default=60)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    items = asyncio.run(build(args.real, args.perturbed, args.fabricated, args.seed))
    save(items, args.out)
    by_label: dict[str, int] = {}
    for it in items:
        by_label[it.label.value] = by_label.get(it.label.value, 0) + 1
    print(f"wrote {len(items)} items to {args.out}: {by_label}")


if __name__ == "__main__":
    main()
