"""Record linkage: field features and P(same work).

The weights are hand-set starting points; `eval/` refits them on CiteBench and the fitted
values can be loaded through `LinkageModel.from_weights`."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from citeguard.domain.models import MatchFeatures, ParsedReference, Record
from citeguard.match.names import compare_authors
from citeguard.match.normalize import title_similarity
from citeguard.match.venues import venue_similarity
from citeguard.parse.identifiers import normalize_arxiv_id, normalize_doi


def _first_page(pages: str | None) -> str | None:
    if not pages:
        return None
    m = re.search(r"[A-Za-z]?\d+", pages)
    return m.group(0).lower() if m else None


def compute_features(ref: ParsedReference, rec: Record) -> MatchFeatures:
    title_sim = title_similarity(ref.title, rec.title) if ref.title else 0.0
    authors = compare_authors(ref.authors, rec.authors, ref.authors_truncated)

    year_delta = None
    if ref.year and rec.year:
        year_delta = abs(ref.year - rec.year)

    id_match: bool | None = None
    claimed_doi, rec_doi = normalize_doi(ref.ids.doi), normalize_doi(rec.doi)
    if claimed_doi and rec_doi:
        id_match = claimed_doi == rec_doi
    claimed_ax, rec_ax = normalize_arxiv_id(ref.ids.arxiv_id), normalize_arxiv_id(rec.arxiv_id)
    if claimed_ax and rec_ax:
        id_match = (id_match is not False) and claimed_ax == rec_ax

    pages_match = None
    fp_a, fp_b = _first_page(ref.pages), _first_page(rec.pages)
    if fp_a and fp_b:
        pages_match = fp_a == fp_b
    volume_match = None
    if ref.volume and rec.volume:
        volume_match = ref.volume.strip().lower() == rec.volume.strip().lower()

    return MatchFeatures(
        title_sim=title_sim,
        first_author=None
        if authors.first_author_match is None
        else float(authors.first_author_match),
        author_f1=authors.f1,
        author_order=authors.order_score,
        year_delta=year_delta,
        venue_sim=venue_similarity(ref.container_title, rec.container_title),
        id_match=id_match,
        pages_match=pages_match,
        volume_match=volume_match,
    )


@dataclass(frozen=True)
class LinkageModel:
    bias: float = -4.0
    w_title: float = 14.0  # applied to (title_sim - 0.5)
    w_author_f1: float = 3.0
    w_first_author: float = 1.0
    author_offset: float = -2.0
    year_exact: float = 0.7
    year_off_by_one: float = 0.2
    year_off_by_two: float = -0.5
    year_far: float = -1.5
    venue_good: float = 0.5
    venue_bad: float = -0.3
    id_agree: float = 4.0
    id_disagree: float = -1.0

    @classmethod
    def from_weights(cls, weights: dict[str, float]) -> LinkageModel:
        return cls(**weights)

    def logit(self, f: MatchFeatures) -> float:
        z = self.bias + self.w_title * (f.title_sim - 0.5)
        if f.author_f1 is not None:
            z += self.w_author_f1 * f.author_f1 + self.w_first_author * (f.first_author or 0.0)
            z += self.author_offset
        if f.year_delta is not None:
            if f.year_delta == 0:
                z += self.year_exact
            elif f.year_delta == 1:
                z += self.year_off_by_one
            elif f.year_delta == 2:
                z += self.year_off_by_two
            else:
                z += self.year_far
        if f.venue_sim is not None:
            if f.venue_sim >= 0.8:
                z += self.venue_good
            elif f.venue_sim < 0.5:
                z += self.venue_bad
        if f.id_match is True:
            z += self.id_agree
        elif f.id_match is False:
            z += self.id_disagree
        return z

    def probability(self, f: MatchFeatures) -> float:
        return round(1.0 / (1.0 + math.exp(-self.logit(f))), 4)


DEFAULT_MODEL = LinkageModel()

MATCH_THRESHOLD = 0.9
AMBIGUOUS_THRESHOLD = 0.5
STRONG_TITLE = 0.93
