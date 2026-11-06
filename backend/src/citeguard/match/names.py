"""Author name parsing and comparison."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from citeguard.domain.models import Author
from citeguard.match.normalize import fold, latex_to_text

PARTICLES = {
    "van", "von", "der", "den", "de", "del", "della", "di", "da", "la", "le", "du",
    "dos", "das", "ten", "ter", "al", "el", "bin", "ibn", "st", "mac",
}  # fmt: skip
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "phd", "md"}
_ET_AL_RE = re.compile(r"\bet\.?\s*al\.?|\band others\b|…|\.\.\.", re.IGNORECASE)
_DBLP_HOMONYM_RE = re.compile(r"\s+\d{4}$")


def has_et_al(text: str) -> bool:
    return bool(_ET_AL_RE.search(text))


_PARTICLE_INITIALS_RE = re.compile(r"[A-Z](?:[a-z]?[A-Z]){1,3}")  # "BVdS" (dos Santos)


def _is_initials(token: str) -> bool:
    """ "A.", "A. B.", "J.-P.", "Ł." (dotted); bare "A", "AB" or "BVdS" only as single tokens."""
    t = token.strip()
    parts = [p for p in re.split(r"[.\s\-]+", t) if p]
    if not 1 <= len(parts) <= 4:
        return False
    max_len = 2 if "." in t else 1
    if "." not in t and len(parts) == 1 and len(parts[0]) <= 3 and parts[0].isupper():
        return True  # Vancouver "JA"
    if "." not in t and len(parts) == 1 and _PARTICLE_INITIALS_RE.fullmatch(t):
        return True  # Vancouver with particles: "BVdS", "FVSD"
    return all(len(p) <= max_len and p[0].isupper() for p in parts)


def _is_cjk(token: str) -> bool:
    return any(
        "\u4e00" <= ch <= "\u9fff"  # CJK unified ideographs
        or "\u3400" <= ch <= "\u4dbf"
        or "\u3040" <= ch <= "\u30ff"  # hiragana / katakana
        or "\uac00" <= ch <= "\ud7af"  # hangul
        for ch in token
    )


def parse_name(raw: str) -> Author | None:
    """Parse a single personal name in any common citation form."""
    name = latex_to_text(raw)
    name = _DBLP_HOMONYM_RE.sub("", name)  # DBLP disambiguation suffix: "Wei Wang 0001"
    name = _ET_AL_RE.sub("", name).strip(" ,;.")
    if not name or not re.search(r"[A-Za-zÀ-ÿĀ-￿]", name):
        return None

    if "," in name:  # "Family, Given" / "Family, G. G." / "Family, Jr., Given"
        parts = [p.strip() for p in name.split(",") if p.strip()]
        parts = [p for p in parts if fold(p) not in SUFFIXES] or parts
        family = parts[0]
        given = " ".join(parts[1:]) or None
        return Author(family=family, given=given)

    tokens = name.split()
    tokens = [t for t in tokens if fold(t) not in SUFFIXES] or tokens
    if len(tokens) == 1:
        return Author(family=tokens[0])
    if all(_is_cjk(t) for t in tokens):  # Chinese / Japanese / Korean order: family first
        return Author(family=tokens[0], given=" ".join(tokens[1:]))
    # Vancouver / PubMed: "Smith JA"
    last = tokens[-1].replace(".", "")
    if (
        len(tokens) >= 2
        and _is_initials(tokens[-1])
        and (last.isupper() or _PARTICLE_INITIALS_RE.fullmatch(last))
    ):
        return Author(family=" ".join(tokens[:-1]), given=tokens[-1])
    # "Given [particles] Family"
    i = len(tokens) - 1
    while i > 1 and fold(tokens[i - 1]) in PARTICLES:
        i -= 1
    family = " ".join(tokens[i:])
    given = " ".join(tokens[:i]) or None
    return Author(family=family, given=given)


def split_author_list(text: str) -> tuple[list[Author], bool]:
    """Split a free-text author list. Returns (authors, truncated_with_et_al)."""
    truncated = has_et_al(text)
    text = latex_to_text(_ET_AL_RE.sub("", text)).strip(" ,;.")
    if not text:
        return [], truncated
    text = re.sub(r"\s*(?:,\s*)?(?:&|\band\b)\s*", ", ", text)

    if ";" in text:
        chunks = [c.strip() for c in text.split(";")]
        return [a for c in chunks if c and (a := parse_name(c))], truncated

    tokens = [t.strip() for t in text.split(",") if t.strip()]
    # "Family, I., Family, I." → pair surname tokens with the initials that follow them.
    if len(tokens) >= 2 and all(_is_initials(tokens[k]) for k in range(1, len(tokens), 2)):
        authors = []
        for k in range(0, len(tokens), 2):
            given = tokens[k + 1] if k + 1 < len(tokens) else None
            authors.append(Author(family=tokens[k], given=given))
        return authors, truncated
    return [a for t in tokens if (a := parse_name(t))], truncated


def family_key(author: Author) -> str:
    # Keep letters of every script (Chinese, Armenian, Cyrillic…), not just a-z.
    return "".join(ch for ch in fold(author.family) if ch.isalpha())


def _is_latin(key: str) -> bool:
    return key.isascii()


def _given_key(author: Author) -> str:
    return "".join(ch for ch in fold(author.given or "") if ch.isalpha())


def _same_person(a: Author, b: Author) -> bool:
    fa, fb = family_key(a), family_key(b)
    if not fa or not fb:
        return False
    if fa == fb or fuzz.ratio(fa, fb) >= 85:
        return True
    # Family/given swapped (common for East-Asian names) or compound family names.
    ga, gb = _given_key(a), _given_key(b)
    if ga and fb and (ga == fb) and gb and gb == fa:
        return True
    if _is_cjk(fa) and _is_cjk(fb):
        # Sources disagree on CJK name order ("杨 怡" vs OpenAlex's "怡飞 杨") and sometimes on
        # the given name itself, so match on the family name appearing in either position.
        return fa in (fb, gb) or fb in (fa, ga)
    return len(fa) >= 4 and len(fb) >= 4 and (fa in fb or fb in fa)


@dataclass
class AuthorComparison:
    first_author_match: bool | None
    f1: float | None
    order_score: float | None
    matched: int = 0
    precision: float | None = None  # share of the listed authors who are on the paper
    claimed_unmatched: list[Author] = field(default_factory=list)
    actual_unmatched: list[Author] = field(default_factory=list)


def compare_authors(
    claimed: list[Author], actual: list[Author], claimed_truncated: bool = False
) -> AuthorComparison:
    if not claimed or not actual:
        return AuthorComparison(first_author_match=None, f1=None, order_score=None)
    # Native script vs. transliteration (杨 怡 vs. Yi Yang) cannot be compared by spelling:
    # report "unknown" rather than "different" so real papers are not called misattributed.
    claimed_latin = {_is_latin(family_key(a)) for a in claimed if family_key(a)}
    actual_latin = {_is_latin(family_key(a)) for a in actual if family_key(a)}
    if len(claimed_latin) == 1 and len(actual_latin) == 1 and claimed_latin != actual_latin:
        return AuthorComparison(first_author_match=None, f1=None, order_score=None)

    used: set[int] = set()
    pairs: list[tuple[int, int]] = []
    for i, ca in enumerate(claimed):
        for j, aa in enumerate(actual):
            if j not in used and _same_person(ca, aa):
                used.add(j)
                pairs.append((i, j))
                break
    matched = len(pairs)
    precision = matched / len(claimed)
    # If the citation says "et al.", or every listed author is on the paper (a BibTeX entry
    # with the first two of eight authors), omitted authors are not evidence of a different work.
    truncated = claimed_truncated or matched == len(claimed)
    denom_actual = min(len(actual), len(claimed)) if truncated else len(actual)
    recall = min(1.0, matched / denom_actual) if denom_actual else 0.0
    f1 = 0.0 if matched == 0 else 2 * precision * recall / (precision + recall)

    order = None
    if len(pairs) >= 2:
        concordant = sum(
            1
            for x in range(len(pairs))
            for y in range(x + 1, len(pairs))
            if (pairs[x][0] - pairs[y][0]) * (pairs[x][1] - pairs[y][1]) > 0
        )
        total = len(pairs) * (len(pairs) - 1) / 2
        order = concordant / total

    matched_claimed = {i for i, _ in pairs}
    return AuthorComparison(
        first_author_match=_same_person(claimed[0], actual[0]),
        f1=round(f1, 4),
        order_score=order,
        matched=matched,
        precision=round(precision, 4),
        claimed_unmatched=[a for i, a in enumerate(claimed) if i not in matched_claimed],
        actual_unmatched=[a for j, a in enumerate(actual) if j not in used],
    )


def format_authors_short(authors: list[Author], limit: int = 3) -> str:
    if not authors:
        return "unknown authors"
    names = [a.family for a in authors[:limit]]
    suffix = " et al." if len(authors) > limit else ""
    return ", ".join(names) + suffix
