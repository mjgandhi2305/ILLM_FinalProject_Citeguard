"""GROBID client: PDF → structured references (TEI `biblStruct`) with citation contexts."""

from __future__ import annotations

import re

import httpx
from defusedxml import ElementTree

from citeguard.domain.models import Author, CitationType, Identifiers, ParsedReference
from citeguard.parse.identifiers import normalize_arxiv_id, normalize_doi

TEI = {"tei": "http://www.tei-c.org/ns/1.0"}


def _text(el: object) -> str | None:
    if el is None:
        return None
    value = " ".join("".join(el.itertext()).split())  # type: ignore[attr-defined]
    return value or None


def bibl_to_reference(bibl: object) -> ParsedReference | None:
    find = bibl.find  # type: ignore[attr-defined]
    findall = bibl.findall  # type: ignore[attr-defined]
    analytic, monogr = find("tei:analytic", TEI), find("tei:monogr", TEI)
    title = _text(analytic.find("tei:title", TEI)) if analytic is not None else None
    container = _text(monogr.find("tei:title", TEI)) if monogr is not None else None
    if not title:
        title, container = container, None
    authors = []
    for pers in findall(".//tei:analytic/tei:author/tei:persName", TEI) or findall(
        ".//tei:monogr/tei:author/tei:persName", TEI
    ):
        family = _text(pers.find("tei:surname", TEI))
        given = (
            " ".join(filter(None, (_text(f) for f in pers.findall("tei:forename", TEI)))) or None
        )
        if family:
            authors.append(Author(family=family, given=given))
    date = bibl.find(".//tei:imprint/tei:date", TEI)  # type: ignore[attr-defined]
    year = None
    if date is not None:
        m = re.search(r"\d{4}", date.get("when", "") or (_text(date) or ""))
        year = int(m.group(0)) if m else None

    def scope(unit: str) -> str | None:
        el = bibl.find(f".//tei:imprint/tei:biblScope[@unit='{unit}']", TEI)  # type: ignore[attr-defined]
        if el is None:
            return None
        if el.get("from"):
            return f"{el.get('from')}-{el.get('to')}" if el.get("to") else el.get("from")
        return _text(el)

    idnos = {i.get("type", "").lower(): _text(i) for i in findall(".//tei:idno", TEI)}
    raw_note = bibl.find("tei:note[@type='raw_reference']", TEI)  # type: ignore[attr-defined]
    raw = _text(raw_note) or ", ".join(
        filter(None, [", ".join(a.display() for a in authors), title, container, str(year or "")])
    )
    if not title and not raw:
        return None
    level = (
        monogr.find("tei:title", TEI).get("level")
        if monogr is not None and monogr.find("tei:title", TEI) is not None
        else None
    )
    ctype = {
        "j": CitationType.ARTICLE_JOURNAL,
        "m": CitationType.BOOK if analytic is None else CitationType.PAPER_CONFERENCE,
    }.get(level or "", CitationType.UNKNOWN)
    arxiv = normalize_arxiv_id(idnos.get("arxiv"))
    if arxiv and (not container or "arxiv" in container.lower()):
        ctype = CitationType.PREPRINT
    return ParsedReference(
        raw=raw,
        authors=authors,
        title=title,
        container_title=container,
        year=year,
        volume=scope("volume"),
        issue=scope("issue"),
        pages=scope("page"),
        type=ctype,
        ids=Identifiers(
            doi=normalize_doi(idnos.get("doi")), arxiv_id=arxiv, pmid=idnos.get("pmid")
        ),
        parse_method="grobid",
        parse_confidence=0.85 if title else 0.4,
        key=bibl.get("{http://www.w3.org/XML/1998/namespace}id"),  # type: ignore[attr-defined]
    )


def tei_to_references(tei_xml: str) -> list[ParsedReference]:
    root = ElementTree.fromstring(tei_xml)
    refs = []
    for bibl in root.findall(".//tei:listBibl/tei:biblStruct", TEI):
        ref = bibl_to_reference(bibl)
        if ref is not None:
            refs.append(ref)
    # In-text contexts: <ref type="bibr" target="#b3">…</ref> inside body paragraphs/sentences.
    by_key = {r.key: r for r in refs if r.key}
    for p in root.findall(".//tei:body//tei:p", TEI):
        sentence = _text(p) or ""
        for ref_el in p.findall(".//tei:ref[@type='bibr']", TEI):
            key = (ref_el.get("target") or "").lstrip("#")
            if key in by_key and len(by_key[key].contexts) < 3 and sentence:
                by_key[key].contexts.append(sentence[:600])
    return refs


async def grobid_references(
    base_url: str, pdf: bytes, timeout_s: float = 120.0
) -> list[ParsedReference]:
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.post(
            f"{base_url.rstrip('/')}/api/processFulltextDocument",
            files={"input": ("paper.pdf", pdf, "application/pdf")},
            data={"includeRawCitations": "1", "consolidateCitations": "0"},
        )
        resp.raise_for_status()
        return tei_to_references(resp.text)
