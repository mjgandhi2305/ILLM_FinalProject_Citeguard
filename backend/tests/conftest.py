from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

import httpx
import pytest

from citeguard.domain.models import Author, CitationType, LookupStatus, Record
from citeguard.match.normalize import title_similarity
from citeguard.sources.base import IdKind, SearchQuery, Source, SourceResponse
from citeguard.sources.doi_org import DoiOrg
from citeguard.sources.http import SourceHttp
from citeguard.sources.infra import CircuitBreaker, MemoryCache, TokenBucket
from citeguard.sources.registry import SourceSet


def rec(
    title: str,
    authors: list[str],
    year: int,
    venue: str | None = None,
    *,
    source: str = "crossref",
    doi: str | None = None,
    arxiv_id: str | None = None,
    rtype: CitationType = CitationType.ARTICLE_JOURNAL,
    retracted: bool | None = None,
    volume: str | None = None,
    pages: str | None = None,
) -> Record:
    parsed = []
    for a in authors:
        given, _, family = a.rpartition(" ")
        parsed.append(Author(family=family, given=given or None))
    return Record(
        source=source,
        source_id=doi or title,
        title=title,
        authors=parsed,
        year=year,
        container_title=venue,
        doi=doi,
        arxiv_id=arxiv_id,
        type=rtype,
        is_retracted=retracted,
        volume=volume,
        pages=pages,
    )


def _dummy_http(name: str) -> SourceHttp:
    return SourceHttp(
        name,
        httpx.AsyncClient(),
        TokenBucket(1000),
        MemoryCache(),
        CircuitBreaker(name),
    )


class FakeSource(Source):
    """In-memory source: search returns corpus records whose title resembles the query."""

    display_name: ClassVar[str] = "Fake"
    lookup_kinds: ClassVar[frozenset[str]] = frozenset({"doi", "arxiv"})

    def __init__(
        self,
        name: str,
        corpus: list[Record],
        *,
        tier: str = "general",
        down: bool = False,
    ) -> None:
        super().__init__(_dummy_http(name), "test@example.org")
        self._name = name
        self.corpus = [r.model_copy(update={"source": name}) for r in corpus]
        self._tier = tier
        self.down = down
        self.calls: list[str] = []

    @property  # type: ignore[override]
    def name(self) -> str:  # type: ignore[override]
        return self._name

    @property  # type: ignore[override]
    def tier(self) -> str:  # type: ignore[override]
        return self._tier

    async def lookup(self, kind: IdKind, value: str) -> SourceResponse:
        self.calls.append(f"lookup:{kind}:{value}")
        if self.down:
            return SourceResponse(status=LookupStatus.ERROR, note="down")
        for r in self.corpus:
            if (kind == "doi" and r.doi == value) or (kind == "arxiv" and r.arxiv_id == value):
                return SourceResponse(status=LookupStatus.FOUND, records=[r])
        return SourceResponse(status=LookupStatus.NOT_FOUND)

    async def search(self, query: SearchQuery, limit: int = 5) -> SourceResponse:
        self.calls.append(f"search:{query.describe()}")
        if self.down:
            return SourceResponse(status=LookupStatus.ERROR, note="down")
        if query.author and not query.title:  # author-driven search (Crossref query.author)
            hits = [r for r in self.corpus if any(a.family in query.author for a in r.authors)][
                :limit
            ]
        else:
            q = query.title or query.text or ""
            hits = sorted(self.corpus, key=lambda r: -title_similarity(q, r.title))
            hits = [r for r in hits if title_similarity(q, r.title) > 0.3][:limit]
        return SourceResponse(
            status=LookupStatus.FOUND if hits else LookupStatus.NOT_FOUND, records=hits
        )


class FakeDoi(DoiOrg):
    def __init__(self, registered: dict[str, Record | None]) -> None:
        super().__init__(_dummy_http("doi"), "test@example.org")
        self.registry = registered

    async def registered(self, doi: str) -> SourceResponse:
        if doi in self.registry:
            return SourceResponse(status=LookupStatus.FOUND, note="registered")
        return SourceResponse(status=LookupStatus.NOT_FOUND, note="not registered")

    async def lookup(self, kind: IdKind, value: str) -> SourceResponse:
        record = self.registry.get(value)
        if record is None:
            return SourceResponse(status=LookupStatus.NOT_FOUND)
        return SourceResponse(
            status=LookupStatus.FOUND, records=[record.model_copy(update={"source": "doi"})]
        )


ATTENTION = rec(
    "Attention Is All You Need",
    ["Ashish Vaswani", "Noam Shazeer", "Niki Parmar", "Jakob Uszkoreit"],
    2017,
    "Advances in Neural Information Processing Systems",
    rtype=CitationType.PAPER_CONFERENCE,
)
DEEP_LEARNING = rec(
    "Deep learning",
    ["Yann LeCun", "Yoshua Bengio", "Geoffrey Hinton"],
    2015,
    "Nature",
    doi="10.1038/nature14539",
    volume="521",
    pages="436-444",
)
BERT = rec(
    "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
    ["Jacob Devlin", "Ming-Wei Chang", "Kenton Lee", "Kristina Toutanova"],
    2019,
    "North American Chapter of the Association for Computational Linguistics",
    rtype=CitationType.PAPER_CONFERENCE,
)
OTHER_HINTON = rec(
    "A fast learning algorithm for deep belief nets",
    ["Geoffrey Hinton", "Simon Osindero", "Yee-Whye Teh"],
    2006,
    "Neural Computation",
    doi="10.1162/neco.2006.18.7.1527",
)
RETRACTED = rec(
    "Ileal-lymphoid-nodular hyperplasia, non-specific colitis, and pervasive developmental disorder in children",
    ["Andrew Wakefield", "Simon Murch"],
    1998,
    "The Lancet",
    doi="10.1016/s0140-6736(97)11096-0",
    retracted=True,
)
CORPUS = [ATTENTION, DEEP_LEARNING, BERT, OTHER_HINTON, RETRACTED]


@pytest.fixture
def make_sources() -> Callable[..., SourceSet]:
    def _make(
        corpus: list[Record] | None = None,
        *,
        down: tuple[str, ...] = (),
        registry: dict[str, Record | None] | None = None,
    ) -> SourceSet:
        corpus = CORPUS if corpus is None else corpus
        names = ["crossref", "openalex", "semantic_scholar"]
        by_name: dict[str, Source] = {n: FakeSource(n, corpus, down=n in down) for n in names}
        by_name["arxiv"] = FakeSource("arxiv", corpus, tier="specialist", down="arxiv" in down)
        reg = registry if registry is not None else {r.doi: r for r in corpus if r.doi}
        return SourceSet(doi=FakeDoi(reg), by_name=by_name)

    return _make
