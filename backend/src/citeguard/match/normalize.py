"""Text normalization and title similarity."""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

from pylatexenc.latex2text import LatexNodes2Text
from rapidfuzz import fuzz

_latex = LatexNodes2Text(math_mode="text", strict_latex_spaces=False)
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")
_HTML_TAG_RE = re.compile(r"<[^>]{1,40}>")


def latex_to_text(value: str) -> str:
    if "\\" not in value and "{" not in value and "$" not in value:
        return value
    try:
        return str(_latex.latex_to_text(value))
    except Exception:  # pylatexenc can choke on malformed input; fall back to raw text
        return value.replace("{", "").replace("}", "")


def strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


@lru_cache(maxsize=8192)
def fold(value: str) -> str:
    """Lowercase, accent-free, punctuation-free, single-spaced."""
    value = _HTML_TAG_RE.sub(" ", value)  # Crossref titles may contain <i>, <sub> ...
    value = latex_to_text(value)
    value = unicodedata.normalize("NFKC", value)
    value = strip_accents(value).lower().replace("&", " and ")
    value = value.replace("_", " ")
    value = _PUNCT_RE.sub(" ", value)
    return _WS_RE.sub(" ", value).strip()


def normalize_title(value: str | None) -> str:
    return fold(value) if value else ""


def main_title(value: str) -> str:
    """Title without its subtitle ("Main: Sub" or "Main - Sub")."""
    for sep in (":", " - ", " — ", " – ", "?"):
        if sep in value:
            head = value.split(sep, 1)[0]
            if len(head.split()) >= 3:
                return head
    return value


def title_similarity(a: str | None, b: str | None) -> float:
    """Similarity in [0, 1]. Robust to case, punctuation, LaTeX, word order and subtitles,
    but *not* to one title being a short prefix of the other (no token_set_ratio)."""
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    score = max(fuzz.ratio(na, nb), fuzz.token_sort_ratio(na, nb)) / 100.0
    # Subtitle tolerance: one citation drops the subtitle of the other.
    ma, mb = normalize_title(main_title(a or "")), normalize_title(main_title(b or ""))
    if ma and mb and (ma == nb or mb == na or (ma == mb and len(ma.split()) >= 4)):
        score = max(score, 0.95)
    return round(score, 4)


def word_count(value: str | None) -> int:
    return len(normalize_title(value).split()) if value else 0
