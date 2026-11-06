"""Built-in citation formatter (APA 7, IEEE, BibTeX). Deterministic and offline."""

from __future__ import annotations

import re
from collections.abc import Sequence

from citeguard.domain.models import Author, CitationType, Record
from citeguard.match.normalize import fold


def _initials(given: str | None) -> str:
    if not given:
        return ""
    parts = re.split(r"[\s]+", given.replace(".", ". ").strip())
    out = []
    for p in parts:
        p = p.strip(".")
        if not p:
            continue
        if "-" in p:
            out.append("-".join(f"{x[0]}." for x in p.split("-") if x))
        else:
            out.append(f"{p[0]}.")
    return " ".join(out)


def _apa_author(a: Author) -> str:
    ini = _initials(a.given)
    return f"{a.family}, {ini}" if ini else a.family


def _apa_authors(authors: list[Author]) -> str:
    if not authors:
        return ""
    names = [_apa_author(a) for a in authors]
    if len(names) == 1:
        return names[0]
    if len(names) <= 20:
        return ", ".join(names[:-1]) + ", & " + names[-1]
    return ", ".join(names[:19]) + ", ... " + names[-1]


def _ieee_author(a: Author) -> str:
    ini = _initials(a.given)
    return f"{ini} {a.family}".strip()


def _ieee_authors(authors: list[Author]) -> str:
    names = [_ieee_author(a) for a in authors]
    if len(names) > 6:
        return names[0] + " et al."
    if len(names) <= 2:
        return " and ".join(names)
    return ", ".join(names[:-1]) + ", and " + names[-1]


def _pages(pages: str | None) -> str | None:
    return re.sub(r"\s*[-–—]+\s*", "–", pages) if pages else None


def format_apa(r: Record) -> str:
    parts = []
    authors = _apa_authors(r.authors)
    parts.append(f"{authors} ({r.year or 'n.d.'}).")
    parts.append(f"{(r.title or '').rstrip('.')}.")
    if r.container_title:
        venue = r.container_title
        if r.volume:
            venue += f", {r.volume}"
            if r.issue:
                venue += f"({r.issue})"
        if r.pages:
            venue += f", {_pages(r.pages)}"
        parts.append(venue + ".")
    elif r.publisher and r.type in (CitationType.BOOK, CitationType.REPORT):
        parts.append(f"{r.publisher}.")
    if r.doi:
        parts.append(f"https://doi.org/{r.doi}")
    elif r.arxiv_id:
        parts.append(f"https://arxiv.org/abs/{r.arxiv_id}")
    elif r.url:
        parts.append(r.url)
    return " ".join(p for p in parts if p.strip(". "))


def format_ieee(r: Record) -> str:
    authors = _ieee_authors(r.authors)
    out = f'{authors}, "{(r.title or "").rstrip(".")},"'
    if r.container_title:
        prefix = "in " if r.type == CitationType.PAPER_CONFERENCE else ""
        out += f" {prefix}{r.container_title},"
    if r.volume:
        out += f" vol. {r.volume},"
    if r.issue:
        out += f" no. {r.issue},"
    if r.pages:
        out += f" pp. {_pages(r.pages)},"
    out += f" {r.year or 'n.d.'}"
    if r.doi:
        out += f", doi: {r.doi}"
    elif r.arxiv_id:
        out += f", arXiv:{r.arxiv_id}"
    return out + "."


def bibtex_key(r: Record) -> str:
    family = fold(r.authors[0].family).replace(" ", "") if r.authors else "anon"
    word = next((w for w in fold(r.title or "").split() if len(w) > 3), "work")
    return f"{family}{r.year or ''}{word}"


def _bib_escape(value: str) -> str:
    return value.replace("{", r"\{").replace("}", r"\}")


def format_bibtex(r: Record) -> str:
    entry_type = {
        CitationType.ARTICLE_JOURNAL: "article",
        CitationType.PAPER_CONFERENCE: "inproceedings",
        CitationType.BOOK: "book",
        CitationType.CHAPTER: "incollection",
        CitationType.THESIS: "phdthesis",
        CitationType.REPORT: "techreport",
    }.get(r.type, "misc")
    fields: list[tuple[str, str]] = [("title", f"{{{_bib_escape(r.title or '')}}}")]
    if r.authors:
        fields.append(
            (
                "author",
                " and ".join(f"{a.family}, {a.given}" if a.given else a.family for a in r.authors),
            )
        )
    if r.container_title:
        key = "booktitle" if entry_type in ("inproceedings", "incollection") else "journal"
        fields.append((key, r.container_title))
    for name, value in (
        ("year", r.year),
        ("volume", r.volume),
        ("number", r.issue),
        ("pages", r.pages.replace("–", "--").replace("-", "--") if r.pages else None),
        ("publisher", r.publisher),
        ("doi", r.doi),
    ):
        if value:
            fields.append((name, str(value)))
    if r.arxiv_id:
        fields += [("eprint", r.arxiv_id), ("archivePrefix", "arXiv")]
    body = ",\n".join(
        f"  {k} = {{{v}}}" if not v.startswith("{") else f"  {k} = {v}" for k, v in fields
    )
    return f"@{entry_type}{{{bibtex_key(r)},\n{body}\n}}"


FORMATTERS = {"apa": format_apa, "ieee": format_ieee, "bibtex": format_bibtex}


def format_record(r: Record, styles: Sequence[str]) -> dict[str, str]:
    return {s: FORMATTERS[s](r) for s in styles if s in FORMATTERS}
