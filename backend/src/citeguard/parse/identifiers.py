"""Deterministic identifier extraction. Identifiers found here are authoritative: no later
stage (LLM included) is allowed to change them, because a fabricated DOI is evidence."""

from __future__ import annotations

import re
from urllib.parse import unquote

from citeguard.domain.models import Identifiers

# DOI: "10." + registrant code + "/" + suffix. Suffix may contain almost anything except
# whitespace; we trim trailing punctuation afterwards (see _clean_doi).
_DOI_RE = re.compile(r"(?<![\w/.])(10\.\d{4,9}/[^\s\"<>{}|\\^`]+)", re.IGNORECASE)
_DOI_URL_RE = re.compile(r"(?:https?://)?(?:dx\.)?doi\.org/(10\.\d{4,9}/[^\s\"<>]+)", re.IGNORECASE)

# arXiv identifiers require context ("arXiv:", arxiv.org URL, or the arXiv DOI) so that page
# ranges like "1234.5678" are never mistaken for arXiv IDs.
_ARXIV_NEW_RE = re.compile(
    r"(?:arxiv(?:\s*preprint)?(?:\s*arxiv)?\s*[:/]?\s*|arxiv\.org/(?:abs|pdf)/|10\.48550/arxiv\.)"
    r"(\d{4}\.\d{4,5})(v\d+)?",
    re.IGNORECASE,
)
_ARXIV_OLD_RE = re.compile(
    r"(?:arxiv\s*[:/]?\s*|arxiv\.org/(?:abs|pdf)/)([a-z\-]+(?:\.[a-z]{2})?/\d{7})(v\d+)?",
    re.IGNORECASE,
)
_PMID_RE = re.compile(r"\bPMID\s*:?\s*(\d{1,9})\b", re.IGNORECASE)
_ISBN_RE = re.compile(r"\bISBN(?:-1[03])?\s*:?\s*([\d][\d\- ]{8,16}[\dXx])\b", re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s<>\"]+", re.IGNORECASE)

_TRAILING_PUNCT = ".,;:'\"”’»"


def _clean_doi(doi: str) -> str:
    doi = unquote(doi).strip()
    # Trim trailing punctuation and unbalanced closing brackets: DOIs such as
    # 10.1016/S0140-6736(20)30183-5 legitimately contain balanced parentheses.
    changed = True
    while changed and doi:
        changed = False
        if doi[-1] in _TRAILING_PUNCT:
            doi = doi[:-1]
            changed = True
        for open_c, close_c in ("()", "[]", "{}"):
            if doi.endswith(close_c) and doi.count(close_c) > doi.count(open_c):
                doi = doi[:-1]
                changed = True
    return doi.lower()


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    m = _DOI_URL_RE.search(value) or _DOI_RE.search(value)
    if not m:
        return None
    return _clean_doi(m.group(1))


def is_valid_doi_syntax(doi: str) -> bool:
    return bool(re.fullmatch(r"10\.\d{4,9}/\S+", doi)) and not doi.endswith("/")


def extract_doi(text: str) -> str | None:
    return normalize_doi(text)


def extract_arxiv_id(text: str) -> str | None:
    m = _ARXIV_NEW_RE.search(text)
    if m:
        return m.group(1)
    m = _ARXIV_OLD_RE.search(text)
    if m:
        return m.group(1).lower()
    return None


def normalize_arxiv_id(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    found = extract_arxiv_id(value)
    if found:
        return found
    m = re.fullmatch(r"(\d{4}\.\d{4,5})(v\d+)?", value)
    if m:
        return m.group(1)
    m = re.fullmatch(r"([a-z\-]+(?:\.[a-z]{2})?/\d{7})(v\d+)?", value, re.IGNORECASE)
    if m:
        return m.group(1).lower()
    return None


def arxiv_id_year(arxiv_id: str) -> int | None:
    """Year encoded in an arXiv identifier (YYMM for new style, YYMMNNN for old style)."""
    m = re.fullmatch(r"(\d{2})(\d{2})\.\d{4,5}", arxiv_id)
    if m:
        yy, mm = int(m.group(1)), int(m.group(2))
        return 2000 + yy if 1 <= mm <= 12 else None
    m = re.fullmatch(r"[a-z\-]+(?:\.[a-z]{2})?/(\d{2})(\d{2})\d{3}", arxiv_id, re.IGNORECASE)
    if m:
        yy = int(m.group(1))
        return 1900 + yy if yy >= 91 else 2000 + yy
    return None


def _isbn_checksum_ok(isbn: str) -> bool:
    if len(isbn) == 10:
        total = 0
        for i, ch in enumerate(isbn):
            if ch in "Xx" and i == 9:
                val = 10
            elif ch.isdigit():
                val = int(ch)
            else:
                return False
            total += (10 - i) * val
        return total % 11 == 0
    if len(isbn) == 13 and isbn.isdigit():
        total = sum((1 if i % 2 == 0 else 3) * int(ch) for i, ch in enumerate(isbn))
        return total % 10 == 0
    return False


def extract_isbn(text: str) -> str | None:
    for m in _ISBN_RE.finditer(text):
        digits = re.sub(r"[\s\-]", "", m.group(1))
        if _isbn_checksum_ok(digits):
            return digits.upper()
    return None


def extract_pmid(text: str) -> str | None:
    m = _PMID_RE.search(text)
    return m.group(1) if m else None


def extract_url(text: str) -> str | None:
    for m in _URL_RE.finditer(text):
        url = m.group(0).rstrip(_TRAILING_PUNCT + ")]")
        if "doi.org/" not in url.lower():
            return url
    return None


def extract_identifiers(text: str) -> Identifiers:
    doi = extract_doi(text)
    arxiv_id = extract_arxiv_id(text)
    if doi and doi.startswith("10.48550/arxiv.") and not arxiv_id:
        arxiv_id = normalize_arxiv_id(doi.split("arxiv.", 1)[1])
    return Identifiers(
        doi=doi,
        arxiv_id=arxiv_id,
        pmid=extract_pmid(text),
        isbn=extract_isbn(text),
        url=extract_url(text),
    )


def strip_identifiers(text: str) -> str:
    """Remove identifiers and URLs so heuristic parsing sees only bibliographic text."""
    text = _URL_RE.sub(" ", text)
    text = re.sub(r"\bdoi\s*:?\s*", " ", text, flags=re.IGNORECASE)
    text = _DOI_RE.sub(" ", text)
    text = _ARXIV_NEW_RE.sub(" ", text)
    text = _ARXIV_OLD_RE.sub(" ", text)
    text = _PMID_RE.sub(" ", text)
    text = _ISBN_RE.sub(" ", text)
    return re.sub(r"\s{2,}", " ", text).strip(" .,;")


# Well-known DOI prefixes → publisher, used for consistency screening.
DOI_PREFIX_PUBLISHER: dict[str, str] = {
    "10.1145": "ACM",
    "10.1109": "IEEE",
    "10.1007": "Springer",
    "10.1186": "BioMed Central",
    "10.1016": "Elsevier",
    "10.1038": "Nature Portfolio",
    "10.1126": "Science (AAAS)",
    "10.1371": "PLOS",
    "10.1093": "Oxford University Press",
    "10.1017": "Cambridge University Press",
    "10.1002": "Wiley",
    "10.1111": "Wiley",
    "10.1080": "Taylor & Francis",
    "10.1177": "SAGE",
    "10.3390": "MDPI",
    "10.3389": "Frontiers",
    "10.18653": "ACL Anthology",
    "10.48550": "arXiv",
    "10.1162": "MIT Press",
    "10.1103": "American Physical Society",
    "10.1073": "PNAS",
    "10.1021": "American Chemical Society",
    "10.1056": "NEJM",
    "10.1001": "JAMA Network",
    "10.1136": "BMJ",
    "10.1101": "Cold Spring Harbor (bioRxiv/medRxiv)",
    "10.5281": "Zenodo",
    "10.1609": "AAAI",
    "10.24963": "IJCAI",
    "10.1137": "SIAM",
    "10.1088": "IOP Publishing",
    "10.1063": "AIP Publishing",
    "10.2139": "SSRN",
}


def doi_prefix(doi: str) -> str:
    return doi.split("/", 1)[0]
