"""Request / response models of the public REST API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from citeguard.domain.models import CheckOptions, ClaimSupport, InputKind, Verdict


class CheckCreate(BaseModel):
    """Exactly one of `text`, `bibtex` or `citation`."""

    text: str | None = Field(default=None, max_length=2_000_000)
    bibtex: str | None = Field(default=None, max_length=2_000_000)
    citation: str | None = Field(default=None, max_length=5_000)
    options: CheckOptions = Field(default_factory=CheckOptions)

    @model_validator(mode="after")
    def _exactly_one(self) -> CheckCreate:
        given = [f for f in ("text", "bibtex", "citation") if getattr(self, f)]
        if len(given) != 1:
            raise ValueError("provide exactly one of: text, bibtex, citation")
        if self.options.claim and not self.citation:
            raise ValueError(
                "options.claim is for single-citation input; documents carry their own"
            )
        return self

    def kind_and_content(self) -> tuple[InputKind, str]:
        if self.bibtex:
            return "bibtex", self.bibtex
        if self.citation:
            return "citation", self.citation
        return "text", self.text or ""


class CheckCreated(BaseModel):
    id: uuid.UUID
    status: str
    links: dict[str, str]


class CitationSummary(BaseModel):
    index: int
    verdict: Verdict
    confidence: float
    risk_score: float
    title: str | None
    raw: str
    headline: str | None
    explanation_mode: Literal["template", "llm"] | None
    flags: list[str]
    enriched: bool
    has_correction: bool
    alternatives: int
    claim_support: ClaimSupport | None = Field(
        default=None, description="Most serious claim-check label, when claims were checked"
    )


class CheckOut(BaseModel):
    id: uuid.UUID
    status: Literal["queued", "running", "completed", "failed"]
    input_kind: str
    filename: str | None
    progress_total: int
    progress_done: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    expires_at: datetime
    summary: dict[str, Any] | None
    warnings: list[str]
    error: str | None
    citations: list[CitationSummary]


class CheckListItem(BaseModel):
    id: uuid.UUID
    status: str
    input_kind: str
    filename: str | None
    progress_total: int
    progress_done: int
    created_at: datetime
    summary: dict[str, Any] | None


class FeedbackIn(BaseModel):
    user_verdict: Verdict
    comment: str | None = Field(default=None, max_length=2000)


class FeedbackOut(BaseModel):
    id: uuid.UUID
    received: bool = True


class SourceHealth(BaseModel):
    sources: dict[str, str]
    llm: dict[str, Any]
