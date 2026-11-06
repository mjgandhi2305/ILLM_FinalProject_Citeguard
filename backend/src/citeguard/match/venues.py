"""Venue (journal / conference) normalization with an alias table."""

from __future__ import annotations

import re

from rapidfuzz import fuzz

from citeguard.match.normalize import fold

# canonical key -> aliases (already folded or foldable). Extend freely; evaluation decides.
VENUE_ALIASES: dict[str, list[str]] = {
    "neurips": [
        "neurips", "nips", "advances in neural information processing systems",
        "conference on neural information processing systems",
        "neural information processing systems",
    ],
    "icml": ["icml", "international conference on machine learning"],
    "iclr": ["iclr", "international conference on learning representations"],
    "aistats": ["aistats", "artificial intelligence and statistics"],
    "colt": ["colt", "conference on learning theory"],
    "cvpr": [
        "cvpr", "computer vision and pattern recognition",
        "ieee cvf conference on computer vision and pattern recognition",
        "ieee conference on computer vision and pattern recognition",
    ],
    "iccv": ["iccv", "international conference on computer vision"],
    "eccv": ["eccv", "european conference on computer vision"],
    "acl": [
        "acl", "annual meeting of the association for computational linguistics",
        "association for computational linguistics",
    ],
    "emnlp": ["emnlp", "empirical methods in natural language processing"],
    "naacl": [
        "naacl", "north american chapter of the association for computational linguistics",
    ],
    "tacl": ["tacl", "transactions of the association for computational linguistics"],
    "aaai": ["aaai", "aaai conference on artificial intelligence"],
    "ijcai": ["ijcai", "international joint conference on artificial intelligence"],
    "kdd": ["kdd", "sigkdd", "knowledge discovery and data mining"],
    "www": ["www", "the web conference", "world wide web conference", "world wide web"],
    "sigir": ["sigir", "research and development in information retrieval"],
    "chi": ["chi", "conference on human factors in computing systems",
            "human factors in computing systems"],
    "icse": ["icse", "international conference on software engineering"],
    "jmlr": ["jmlr", "journal of machine learning research"],
    "tpami": ["tpami", "pami", "ieee transactions on pattern analysis and machine intelligence",
              "transactions on pattern analysis and machine intelligence"],
    "tmlr": ["tmlr", "transactions on machine learning research"],
    "pnas": ["pnas", "proceedings of the national academy of sciences",
             "proceedings of the national academy of sciences of the united states of america"],
    "nejm": ["nejm", "new england journal of medicine", "n engl j med"],
    "jama": ["jama", "journal of the american medical association"],
    "bmj": ["bmj", "british medical journal"],
    "lancet": ["lancet", "the lancet"],
    "nature": ["nature"],
    "science": ["science"],
    "cell": ["cell"],
    "plos one": ["plos one", "plos one journal"],
    "arxiv": ["arxiv", "arxiv preprint", "corr", "arxiv org", "computing research repository",
              "arxiv e prints", "arxiv preprints"],
}  # fmt: skip

# Venues that host several conferences' proceedings and so are "compatible" with them.
COMPATIBLE: dict[str, set[str]] = {
    "pmlr": {"icml", "aistats", "colt"},
}

_NOISE_RE = re.compile(
    r"\b(proceedings|proc|of|the|in|on|annual|international|intl|conference|conf|"
    r"symposium|workshop|volume|vol|part|edition|ed)\b"
)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_ORDINAL_RE = re.compile(r"\b\d+(st|nd|rd|th)\b")

_ALIAS_INDEX: dict[str, str] = {}
for _key, _aliases in VENUE_ALIASES.items():
    for _alias in _aliases:
        _ALIAS_INDEX[fold(_alias)] = _key


def _clean(value: str) -> str:
    v = fold(value)
    v = _YEAR_RE.sub(" ", v)
    v = _ORDINAL_RE.sub(" ", v)
    return re.sub(r"\s+", " ", v).strip()


def canonical_venue(value: str | None) -> str | None:
    if not value:
        return None
    v = _clean(value)
    if v in _ALIAS_INDEX:
        return _ALIAS_INDEX[v]
    if "pmlr" in v or "proceedings of machine learning research" in v:
        return "pmlr"
    stripped = re.sub(r"\s+", " ", _NOISE_RE.sub(" ", v)).strip()
    if stripped in _ALIAS_INDEX:
        return _ALIAS_INDEX[stripped]
    # Long alias contained in the venue string ("Proceedings of the 2019 Conference of the
    # North American Chapter of the Association for Computational Linguistics: ...").
    best: str | None = None
    best_len = 0
    for alias, key in _ALIAS_INDEX.items():
        if len(alias) >= 12 and alias in v and len(alias) > best_len:
            best, best_len = key, len(alias)
    if best:
        return best
    # Acronym in parentheses: "... Conference (CVPR)"
    m = re.search(r"\(([A-Za-z]{2,10})\)", value)
    if m and fold(m.group(1)) in _ALIAS_INDEX:
        return _ALIAS_INDEX[fold(m.group(1))]
    return None


# Preprint servers and repositories, as named by Crossref / OpenAlex / S2
# (e.g. "arXiv (Cornell University)", "bioRxiv (Cold Spring Harbor Laboratory)", "Zenodo").
_REPOSITORY_RE = re.compile(
    r"\b(arxiv|corr|biorxiv|medrxiv|chemrxiv|techrxiv|psyarxiv|socarxiv|eartharxiv|ssrn|"
    r"zenodo|figshare|research square|preprints?|osf|authorea|hal|repec|europe pmc)\b"
)


def is_preprint_venue(value: str | None) -> bool:
    if not value:
        return False
    return canonical_venue(value) == "arxiv" or bool(_REPOSITORY_RE.search(fold(value)))


def _abbrev_match(a: str, b: str) -> bool:
    """ISO-4 style abbreviation: "Nat. Mach. Intell." vs "Nature Machine Intelligence"."""
    ta, tb = _clean(a).split(), _clean(b).split()
    ta = [t for t in ta if t not in {"of", "the", "and", "for", "in", "on"}]
    tb = [t for t in tb if t not in {"of", "the", "and", "for", "in", "on"}]
    if not ta or len(ta) != len(tb):
        return False
    return all(x.startswith(y) or y.startswith(x) for x, y in zip(ta, tb, strict=True))


def _acronym(value: str) -> str:
    words = [w for w in _NOISE_RE.sub(" ", fold(value)).split() if w not in {"and", "for"}]
    return "".join(w[0] for w in words)


def venue_similarity(a: str | None, b: str | None) -> float | None:
    """Similarity in [0, 1]; None when either side is missing or a preprint server."""
    if not a or not b:
        return None
    if is_preprint_venue(a) != is_preprint_venue(b):
        return None  # preprint vs published version: not comparable, not a mismatch
    ca, cb = canonical_venue(a), canonical_venue(b)
    if ca and cb:
        if ca == cb or cb in COMPATIBLE.get(ca, set()) or ca in COMPATIBLE.get(cb, set()):
            return 1.0
        return 0.0
    na, nb = _clean(a), _clean(b)
    if na == nb:
        return 1.0
    if _abbrev_match(a, b):
        return 0.9
    short, long_ = sorted((na, nb), key=len)
    if " " not in short and len(short) >= 2 and short == _acronym(long_):
        return 0.9
    sa = re.sub(r"\s+", " ", _NOISE_RE.sub(" ", na)).strip()
    sb = re.sub(r"\s+", " ", _NOISE_RE.sub(" ", nb)).strip()
    return round(max(fuzz.token_sort_ratio(sa, sb), fuzz.partial_ratio(sa, sb) * 0.9) / 100, 4)
