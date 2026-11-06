"""Report exporters: JSON, CSV, Markdown, HTML and a corrected BibTeX bibliography."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from jinja2 import Environment, PackageLoader, select_autoescape

from citeguard.domain.models import CitationResult, Record, Verdict
from citeguard.explain.templates import SOURCE_NAMES
from citeguard.suggest.format import format_bibtex

_env = Environment(
    loader=PackageLoader("citeguard.report", "templates"),
    # Templates are named *.html.j2, which select_autoescape(["html"]) does not match: escape
    # by default. Citation text is user input.
    autoescape=select_autoescape(["html", "html.j2"], default=True),
    trim_blocks=True,
    lstrip_blocks=True,
)


def _safe_url(url: str | None) -> str:
    """Links come from third-party records: only http(s) is allowed (no javascript: URLs)."""
    return url if url and url.lower().startswith(("https://", "http://")) else "#"


_env.filters["safe_url"] = _safe_url

VERDICT_LABEL = {
    Verdict.VERIFIED: "Verified",
    Verdict.VERIFIED_WITH_ERRORS: "Real, with errors",
    Verdict.MISATTRIBUTED: "Misattributed",
    Verdict.FABRICATED: "Likely fabricated",
    Verdict.UNVERIFIABLE: "Unverifiable",
}


CLAIM_LABEL = {
    "SUPPORTS": "Supported",
    "PARTIAL": "Partly supported",
    "NOT_SUPPORTED": "Not supported",
    "CANNOT_DETERMINE": "Cannot tell from the abstract",
}


def to_json(meta: dict[str, Any], citations: Sequence[CitationResult]) -> str:
    return json.dumps(
        {**meta, "citations": [c.model_dump(mode="json") for c in citations]},
        indent=2,
        default=str,
    )


def to_csv(citations: Sequence[CitationResult]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "#",
            "verdict",
            "confidence",
            "title",
            "authors",
            "year",
            "venue",
            "doi",
            "finding",
            "corrected_apa",
            "flags",
            "claim_support",
        ]
    )
    for c in citations:
        ref = c.reference
        fix = next((s for s in c.suggestions if s.kind == "correction"), None)
        w.writerow(
            [
                c.index + 1,
                c.verdict.value,
                f"{c.confidence:.2f}",
                ref.title or "",
                "; ".join(a.display() for a in ref.authors),
                ref.year or "",
                ref.container_title or "",
                ref.ids.doi or "",
                c.explanation.headline if c.explanation else "",
                fix.formatted.get("apa", "") if fix else "",
                " ".join(f.value for f in c.flags),
                " ".join(ch.label.value for ch in c.claim_checks),
            ]
        )
    return buf.getvalue()


def to_markdown(
    meta: dict[str, Any], citations: Sequence[CitationResult], style: str = "apa"
) -> str:
    lines = [f"# Citation check: {meta.get('filename') or meta.get('input_kind', '')}", ""]
    summary = meta.get("summary") or {}
    counts = summary.get("by_verdict", {})
    lines.append(
        f"**{len(citations)} citations** · "
        + " · ".join(f"{VERDICT_LABEL[Verdict(v)]}: {n}" for v, n in counts.items() if n)
    )
    lines.append("")
    for c in citations:
        lines.append(
            f"## {c.index + 1}. {VERDICT_LABEL[c.verdict]} (confidence {c.confidence:.2f})"
        )
        lines.append(f"> {c.reference.raw}")
        if c.explanation:
            lines += ["", f"**{c.explanation.headline}**", ""]
            lines += [f"- {r.text}" for r in c.explanation.reasons]
            lines += ["", f"_{c.explanation.recommendation}_"]
        if c.claim_checks:
            lines += ["", "**Claim check** (abstract only; a hint, not a verdict):"]
            for ch in c.claim_checks:
                lines.append(f"- {CLAIM_LABEL[ch.label.value]}: “{ch.claim}”. {ch.rationale}")
                if ch.quote:
                    lines.append(f"  - Abstract: “{ch.quote}”")
            lines.append("")
        for s in c.suggestions:
            label = "Corrected" if s.kind == "correction" else "Alternative"
            lines.append(f"- **{label}:** {s.formatted.get(style, '')}")
        lines.append("")
    return "\n".join(lines)


def _bib_from_reference(c: CitationResult) -> str:
    ref = c.reference
    rec = Record(
        source="input",
        source_id=ref.key or str(c.index),
        title=ref.title,
        authors=ref.authors,
        year=ref.year,
        container_title=ref.container_title,
        volume=ref.volume,
        issue=ref.issue,
        pages=ref.pages,
        publisher=ref.publisher,
        type=ref.type,
        doi=ref.ids.doi,
        arxiv_id=ref.ids.arxiv_id,
    )
    return format_bibtex(rec)


def _with_key(bibtex: str, key: str | None) -> str:
    if not key:
        return bibtex
    head, _, rest = bibtex.partition(",")
    entry_type = head.split("{", 1)[0]
    return f"{entry_type}{{{key},{rest}"


def to_corrected_bibtex(citations: Sequence[CitationResult]) -> str:
    """Corrected bibliography: real works get verified metadata (original keys kept so the
    manuscript still compiles); fabricated ones are commented out with the reason."""
    out = [
        "% Bibliography corrected by CiteGuard on " + datetime.now().strftime("%Y-%m-%d"),
        "% Review every change before submitting.",
        "",
    ]
    for c in citations:
        key = c.reference.key
        fix = next((s for s in c.suggestions if s.kind == "correction"), None)
        headline = c.explanation.headline if c.explanation else c.verdict.value
        if c.verdict == Verdict.FABRICATED:
            out.append(f"% REMOVED [{c.verdict.value}] {headline}")
            out += ["% " + line for line in _bib_from_reference(c).splitlines()]
            alts = [s for s in c.suggestions if s.kind == "alternative"]
            for s in alts:
                out.append("% Possible replacement: " + s.formatted.get("apa", ""))
        elif fix is not None:
            out.append(f"% CORRECTED [{c.verdict.value}] {headline}")
            out.append(_with_key(fix.formatted.get("bibtex") or format_bibtex(fix.record), key))
        else:
            if c.verdict == Verdict.UNVERIFIABLE:
                out.append(f"% UNVERIFIED: {headline}")
            matched = (
                c.best_match.record if c.best_match and c.verdict == Verdict.VERIFIED else None
            )
            out.append(
                _with_key(format_bibtex(matched) if matched else _bib_from_reference(c), key)
            )
        out.append("")
    return "\n".join(out)


def to_html(meta: dict[str, Any], citations: Sequence[CitationResult], style: str = "apa") -> str:
    template = _env.get_template("report.html.j2")
    return template.render(
        meta=meta,
        citations=citations,
        style=style,
        labels={v.value: VERDICT_LABEL[v] for v in Verdict},
        claim_labels=CLAIM_LABEL,
        source_names=SOURCE_NAMES,
        generated=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )
