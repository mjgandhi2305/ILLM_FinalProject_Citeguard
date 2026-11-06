"""Plain-text / Markdown ingestion: find the reference list, split it into entries and link
in-text citation markers back to entries (claim context for alternatives and claim checks)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_HEADING_RE = re.compile(
    r"^\s{0,3}(?:#{1,6}\s*|\*\*|__)?\s*(?:\d+\.?\s*)?"
    r"(references|bibliography|works cited|literature cited|sources|citations|"
    r"reference list|cited works|further reading)\s*:?\s*(?:\*\*|__)?\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_NUMBERED_BRACKET_RE = re.compile(r"^\s*\[(\d{1,3})\]\s+", re.MULTILINE)
_NUMBERED_DOT_RE = re.compile(r"^\s*(\d{1,3})[.)]\s+", re.MULTILINE)
_BULLET_RE = re.compile(r"^\s*[-*•·]\s+", re.MULTILINE)
_YEAR_RE = re.compile(r"\b(1[6-9]\d{2}|20\d{2})[a-z]?\b")
_AUTHOR_START_RE = re.compile(
    r"^\s*(?:[A-Z][\w'’\-]+(?:\s+[A-Z][\w'’\-]+)?,\s*(?:[A-Z]\.|[A-Z][a-z]+))"
)
_CITE_SIGNAL_RE = re.compile(
    r"\bdoi\b|10\.\d{4,9}/|arxiv|\bjournal\b|\bproceedings\b|\bconference\b|\bvol\.|"
    r"\bpp\.|\bet al\.|[\"“][^\"”]{10,}[\"”]|\*[^*]{4,}\*|\bpress\b|\btransactions\b",
    re.IGNORECASE,
)


@dataclass
class TextReferences:
    entries: list[str]
    labels: list[str | None]
    body: str  # text before the reference list
    contexts: dict[int, list[str]] = field(default_factory=dict)


def _looks_like_citation(chunk: str) -> bool:
    chunk = chunk.strip()
    if len(chunk) < 25:
        return False
    has_year = bool(_YEAR_RE.search(chunk))
    return has_year and bool(_CITE_SIGNAL_RE.search(chunk) or _AUTHOR_START_RE.match(chunk))


def _split_by(pattern: re.Pattern[str], block: str) -> tuple[list[str], list[str | None]]:
    matches = list(pattern.finditer(block))
    entries, labels = [], []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(block)
        text = " ".join(block[m.end() : end].split())
        if text:
            entries.append(text)
            labels.append(m.group(1) if m.groups() else None)
    return entries, labels


def split_entries(block: str) -> tuple[list[str], list[str | None]]:
    for pattern in (_NUMBERED_BRACKET_RE, _NUMBERED_DOT_RE, _BULLET_RE):
        if len(pattern.findall(block)) >= 1:
            entries, labels = _split_by(pattern, block)
            if entries:
                return entries, labels
    paragraphs = [p for p in re.split(r"\n\s*\n", block) if p.strip()]
    if len(paragraphs) > 1:
        return [" ".join(p.split()) for p in paragraphs], [None] * len(paragraphs)
    # One entry per line, joining continuation lines that don't start a new author list.
    lines: list[str] = []
    for line in block.splitlines():
        if not line.strip():
            continue
        if lines and not _AUTHOR_START_RE.match(line) and not _YEAR_RE.search(line[:60]):
            lines[-1] += " " + line.strip()
        else:
            lines.append(line.strip())
    return lines, [None] * len(lines)


def extract_references(text: str) -> TextReferences:
    text = text.replace("\r\n", "\n")
    headings = list(_HEADING_RE.finditer(text))
    if headings:
        last = headings[-1]
        body, block = text[: last.start()], text[last.end() :]
    else:
        body, block = "", text

    entries, labels = split_entries(block)
    kept = [(e, lab) for e, lab in zip(entries, labels, strict=True) if _looks_like_citation(e)]
    if not kept and headings:  # heading matched but entries are terse; trust the heading
        kept = [(e, lab) for e, lab in zip(entries, labels, strict=True) if len(e) >= 20]
    if not headings and not kept:
        # No heading and nothing citation-like line by line: scan sentences of prose.
        lines = [ln.strip() for ln in text.splitlines() if _looks_like_citation(ln)]
        kept = [(ln, None) for ln in lines]
    result = TextReferences(
        entries=[e for e, _ in kept], labels=[lab for _, lab in kept], body=body
    )
    result.contexts = link_contexts(body, result)
    return result


_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\[(])")


def link_contexts(body: str, refs: TextReferences) -> dict[int, list[str]]:
    """Map entry index -> sentences in the body that cite it ([n] markers or Author-Year)."""
    if not body.strip():
        return {}
    sentences = [s.strip() for s in _SENTENCE_RE.split(" ".join(body.split())) if s.strip()]
    contexts: dict[int, list[str]] = {}
    label_to_idx = {lab: i for i, lab in enumerate(refs.labels) if lab}
    for sent in sentences:
        for group in re.findall(r"\[([\d,\s–\-]+)\]", sent):
            for num in _expand_numbers(group):
                idx = label_to_idx.get(str(num))
                if idx is None and not label_to_idx and 1 <= num <= len(refs.entries):
                    idx = num - 1
                if idx is not None:
                    contexts.setdefault(idx, []).append(sent)
        for m in re.finditer(
            r"([A-Z][\w'’\-]+)(?:\s+et al\.?|\s+(?:and|&)\s+[A-Z][\w'’\-]+)?,?\s*\(?((?:19|20)\d{2})",
            sent,
        ):
            surname, year = m.group(1), m.group(2)
            for i, entry in enumerate(refs.entries):
                if year in entry and (entry.startswith(surname) or f" {surname}," in entry[:120]):
                    contexts.setdefault(i, []).append(sent)
    return {k: list(dict.fromkeys(v))[:3] for k, v in contexts.items()}


def _expand_numbers(group: str) -> list[int]:
    nums: list[int] = []
    for part in re.split(r",", group):
        part = part.strip()
        m = re.fullmatch(r"(\d+)\s*[–\-]\s*(\d+)", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if 0 < b - a < 50:
                nums.extend(range(a, b + 1))
        elif part.isdigit():
            nums.append(int(part))
    return nums
