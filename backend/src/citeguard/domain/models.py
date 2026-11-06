"""Core domain models shared by every layer (engine, API, CLI, evaluation)."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class CitationType(StrEnum):
    ARTICLE_JOURNAL = "article-journal"
    PAPER_CONFERENCE = "paper-conference"
    PREPRINT = "preprint"
    BOOK = "book"
    CHAPTER = "chapter"
    THESIS = "thesis"
    REPORT = "report"
    WEBPAGE = "webpage"
    DATASET = "dataset"
    OTHER = "other"
    UNKNOWN = "unknown"


ARTICLE_LIKE = {
    CitationType.ARTICLE_JOURNAL,
    CitationType.PAPER_CONFERENCE,
    CitationType.PREPRINT,
}


class Author(BaseModel):
    family: str
    given: str | None = None

    def display(self) -> str:
        return f"{self.given} {self.family}".strip() if self.given else self.family


class Identifiers(BaseModel):
    doi: str | None = None
    arxiv_id: str | None = None
    pmid: str | None = None
    isbn: str | None = None
    url: str | None = None

    def any(self) -> bool:
        return any((self.doi, self.arxiv_id, self.pmid, self.isbn))


ParseMethod = Literal["bibtex", "grobid", "llm", "heuristic", "structured"]


class ParsedReference(BaseModel):
    """A citation as the *author* wrote it. Never corrected; that is the whole point."""

    raw: str
    authors: list[Author] = Field(default_factory=list)
    authors_truncated: bool = False  # "et al." present
    title: str | None = None
    container_title: str | None = None  # journal / conference / book series
    year: int | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    publisher: str | None = None
    type: CitationType = CitationType.UNKNOWN
    ids: Identifiers = Field(default_factory=Identifiers)
    parse_method: ParseMethod = "heuristic"
    parse_confidence: float = 0.5
    key: str | None = None  # BibTeX key or reference label ("12")
    contexts: list[str] = Field(default_factory=list)  # in-text sentences citing it


class Record(BaseModel):
    """A bibliographic record returned by a scholarly source."""

    source: str
    source_id: str
    url: str | None = None
    title: str | None = None
    authors: list[Author] = Field(default_factory=list)
    year: int | None = None
    container_title: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    publisher: str | None = None
    type: CitationType = CitationType.UNKNOWN
    doi: str | None = None
    arxiv_id: str | None = None
    pmid: str | None = None
    abstract: str | None = None
    is_retracted: bool | None = None
    cited_by: int | None = None


class LookupStatus(StrEnum):
    FOUND = "found"
    NOT_FOUND = "not_found"
    ERROR = "error"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"  # circuit open / disabled


class Evidence(BaseModel):
    """One source interaction, kept as an auditable piece of evidence."""

    id: str  # "ev1", "ev2", ...
    source: str
    operation: Literal["lookup", "search", "registry"]
    query: str
    status: LookupStatus
    records: list[Record] = Field(default_factory=list)
    url: str | None = None  # human-browsable link for this lookup
    latency_ms: int = 0
    cached: bool = False
    note: str | None = None


class Severity(StrEnum):
    INFO = "info"
    MINOR = "minor"
    MAJOR = "major"
    CRITICAL = "critical"


class DiscrepancyCode(StrEnum):
    ID_INVALID_SYNTAX = "ID_INVALID_SYNTAX"
    ID_NOT_REGISTERED = "ID_NOT_REGISTERED"
    ID_RESOLVES_TO_DIFFERENT_WORK = "ID_RESOLVES_TO_DIFFERENT_WORK"
    TITLE_NOT_FOUND = "TITLE_NOT_FOUND"
    TITLE_MISMATCH_MINOR = "TITLE_MISMATCH_MINOR"
    TITLE_MISMATCH_MAJOR = "TITLE_MISMATCH_MAJOR"
    FIRST_AUTHOR_MISMATCH = "FIRST_AUTHOR_MISMATCH"
    AUTHORS_MISSING = "AUTHORS_MISSING"
    AUTHORS_EXTRA = "AUTHORS_EXTRA"
    AUTHORS_FABRICATED = "AUTHORS_FABRICATED"
    AUTHORS_REORDERED = "AUTHORS_REORDERED"
    YEAR_MISMATCH = "YEAR_MISMATCH"
    VENUE_MISMATCH = "VENUE_MISMATCH"
    VOLUME_ISSUE_PAGES_MISMATCH = "VOLUME_ISSUE_PAGES_MISMATCH"
    PAGES_IMPLAUSIBLE = "PAGES_IMPLAUSIBLE"
    ARXIV_ID_DATE_INCONSISTENT = "ARXIV_ID_DATE_INCONSISTENT"
    FUTURE_DATE = "FUTURE_DATE"
    CHIMERIC_TITLE_AUTHORS = "CHIMERIC_TITLE_AUTHORS"
    RETRACTED = "RETRACTED"


class Discrepancy(BaseModel):
    code: DiscrepancyCode
    severity: Severity
    field: str | None = None
    claimed: str | None = None
    actual: str | None = None
    message: str
    evidence_ids: list[str] = Field(default_factory=list)


class Verdict(StrEnum):
    VERIFIED = "VERIFIED"
    VERIFIED_WITH_ERRORS = "VERIFIED_WITH_ERRORS"
    MISATTRIBUTED = "MISATTRIBUTED"
    FABRICATED = "FABRICATED"
    UNVERIFIABLE = "UNVERIFIABLE"


VERDICT_SEVERITY_ORDER = {
    Verdict.FABRICATED: 0,
    Verdict.MISATTRIBUTED: 1,
    Verdict.VERIFIED_WITH_ERRORS: 2,
    Verdict.UNVERIFIABLE: 3,
    Verdict.VERIFIED: 4,
}


class Flag(StrEnum):
    RETRACTED = "RETRACTED"
    PREPRINT_HAS_PUBLISHED_VERSION = "PREPRINT_HAS_PUBLISHED_VERSION"
    CLAIM_NOT_SUPPORTED = "CLAIM_NOT_SUPPORTED"
    LOW_PARSE_CONFIDENCE = "LOW_PARSE_CONFIDENCE"
    LLM_ADJUDICATED = "LLM_ADJUDICATED"
    SOURCES_DEGRADED = "SOURCES_DEGRADED"


class RiskSignal(BaseModel):
    code: str
    message: str
    weight: float


class MatchFeatures(BaseModel):
    title_sim: float
    first_author: float | None = None
    author_f1: float | None = None
    author_order: float | None = None
    year_delta: int | None = None
    venue_sim: float | None = None
    id_match: bool | None = None
    pages_match: bool | None = None
    volume_match: bool | None = None


class Candidate(BaseModel):
    record: Record
    features: MatchFeatures
    probability: float
    evidence_id: str


class Reason(BaseModel):
    text: str
    evidence_ids: list[str] = Field(default_factory=list)


class Explanation(BaseModel):
    headline: str
    reasons: list[Reason] = Field(default_factory=list)
    recommendation: str
    mode: Literal["template", "llm"] = "template"


class FieldDiff(BaseModel):
    field: str
    claimed: str | None
    actual: str | None


class Suggestion(BaseModel):
    kind: Literal["correction", "alternative"]
    record: Record
    formatted: dict[str, str] = Field(default_factory=dict)  # style -> text
    diffs: list[FieldDiff] = Field(default_factory=list)
    relevance_note: str | None = None
    method: Literal["deterministic", "keyword", "llm"] = "deterministic"


class ClaimSupport(StrEnum):
    SUPPORTS = "SUPPORTS"
    PARTIAL = "PARTIAL"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    CANNOT_DETERMINE = "CANNOT_DETERMINE"


class ClaimCheck(BaseModel):
    """Does the cited paper's abstract support the sentence that cites it? A hint, not a verdict:
    only the abstract is read."""

    claim: str  # the citing sentence
    label: ClaimSupport
    rationale: str
    quote: str | None = None  # the abstract passage the judgement rests on (verbatim)
    abstract_source: str | None = None
    abstract_url: str | None = None
    mode: Literal["llm", "none"] = "llm"  # "none": no abstract or no LLM, label is CANNOT_DETERMINE


class LLMUsage(BaseModel):
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_calls: int = 0
    failures: int = 0

    def add(self, other: LLMUsage) -> None:
        self.calls += other.calls
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cached_calls += other.cached_calls
        self.failures += other.failures


class CitationResult(BaseModel):
    index: int
    reference: ParsedReference
    risk_score: float = 0.0
    risk_signals: list[RiskSignal] = Field(default_factory=list)
    verdict: Verdict = Verdict.UNVERIFIABLE
    confidence: float = 0.0
    flags: list[Flag] = Field(default_factory=list)
    discrepancies: list[Discrepancy] = Field(default_factory=list)
    best_match: Candidate | None = None
    candidates: list[Candidate] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    explanation: Explanation | None = None
    suggestions: list[Suggestion] = Field(default_factory=list)
    claim_checks: list[ClaimCheck] = Field(default_factory=list)
    llm_usage: LLMUsage = Field(default_factory=LLMUsage)
    duration_ms: int = 0
    enriched: bool = False

    @property
    def is_problem(self) -> bool:
        return self.verdict in {
            Verdict.FABRICATED,
            Verdict.MISATTRIBUTED,
            Verdict.VERIFIED_WITH_ERRORS,
        }


InputKind = Literal["text", "bibtex", "citation", "pdf", "docx", "latex"]


Style = Literal["apa", "ieee", "bibtex"]


def _all_styles() -> list[Style]:
    return ["apa", "ieee", "bibtex"]


class CheckOptions(BaseModel):
    use_llm: bool = True
    explain: bool = True  # LLM-written explanations (templates are always produced)
    suggest_alternatives: bool = True
    styles: list[Style] = Field(default_factory=_all_styles)
    sources: list[str] | None = None  # None = settings.enabled_sources
    check_claims: bool = Field(
        default=False,
        description="Check whether each real paper's abstract supports the sentences citing it "
        "(needs the LLM and in-text citations; a hint, not a verdict).",
    )
    claim: str | None = Field(
        default=None,
        max_length=2000,
        description="Single-citation input only: the sentence the citation is meant to support. "
        "Implies check_claims.",
    )


class CheckSummary(BaseModel):
    total: int = 0
    by_verdict: dict[str, int] = Field(default_factory=dict)
    flagged: int = 0
    sources_unhealthy: list[str] = Field(default_factory=list)
    llm_usage: LLMUsage = Field(default_factory=LLMUsage)
    llm_mode: Literal["llm", "template", "mixed"] = "template"
    claims_checked: int = 0  # citing sentences checked against abstracts
    claims_not_supported: int = 0


class CheckReport(BaseModel):
    input_kind: InputKind
    citations: list[CitationResult] = Field(default_factory=list)
    summary: CheckSummary = Field(default_factory=CheckSummary)
    pipeline_version: str = "0.1.0"
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    warnings: list[str] = Field(default_factory=list)
