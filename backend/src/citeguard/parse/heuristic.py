"""Rule-based reference-string parser: the last-resort parser when neither GROBID nor the
LLM is available. Handles APA/Harvard, IEEE/MLA (quoted titles), Vancouver and chatbot-style
Markdown references reasonably; it reports its own confidence so callers can escalate."""

from __future__ import annotations

import re

from citeguard.domain.models import CitationType, ParsedReference
from citeguard.match.names import split_author_list
from citeguard.parse.identifiers import extract_identifiers, strip_identifiers

_LEAD_RE = re.compile(r"^\s*(?:\[\d{1,3}\]|\d{1,3}[.)]|[-*•·])\s*")
_YEAR_PAREN_RE = re.compile(r"\((?P<year>(?:1[6-9]|20)\d{2})[a-z]?(?:,[^)]*)?\)")
_YEAR_RE = re.compile(r"\b((?:1[6-9]|20)\d{2})[a-z]?\b")
_QUOTED_RE = re.compile(r"[\"“]([^\"”]{6,})[\"”]")
_BOLD_RE = re.compile(r"\*\*([^*]{6,})\*\*")
_ITALIC_RE = re.compile(r"(?<![*\w])[*_]([^*_]{3,})[*_](?![*\w])")
# Split sentences on ". " but not after an initial ("J. Smith") or common abbreviations
# ("St. Petersburg", "Dr. Who").
_SENT_SPLIT_RE = re.compile(
    r"(?<!\b[A-Z])(?<!\bvol)(?<!\bno)(?<!\bpp)(?<!\bed)(?<!\bSt)(?<!\bMt)(?<!\bDr)(?<!\bvs)"
    r"\.\s+(?=[A-Z0-9\"“*(])"
)

# One Vancouver author: "Smith JA", "Šubic-Kovač M", "Van Tinteren H", "du Plessis E", "Helland Å".
_UPPER = r"[^\W\d_a-z]"  # an uppercase letter in any script (approximately)
_PARTICLE = r"(?:[Vv][ao]n|[Dd]e[nr]?|[Dd]el(?:la)?|[Dd][aiu]|[Dd][oa]s|[Ll][ae]|[Ee]l|[Aa]l|[Tt]e[nr]|[Bb]in|[Ii]bn)"
_FAMILY_WORD = rf"{_UPPER}[\w'’\-‐]+"
_VANCOUVER_AUTHOR = (
    rf"(?:{_PARTICLE}\s){{0,3}}{_FAMILY_WORD}(?:\s{_FAMILY_WORD})?(?:\s[a-z]{{1,3}})?"
    rf"\s{_UPPER}(?:[a-z]?{_UPPER}){{0,3}}(?:,\s*|\.\s+)"  # initials: "JA", "BVdS" (dos Santos)
)
_VANCOUVER_RE = re.compile(rf"^(?P<authors>(?:{_VANCOUVER_AUTHOR})+(?:et al\.\s*)?)(?P<rest>.+)$")
# A "title" that is really the tail of an author list the parser could not read
_AUTHOR_LIST_RE = re.compile(rf"^(?:{_VANCOUVER_AUTHOR}){{2,}}|\bet al\b")
_YEAR_START_RE = re.compile(r"^(?:1[6-9]|20)\d{2}\b")
_LOWER_VENUE_RE = re.compile(r"^(?P<title>.+)\.\s+(?P<venue>[a-z][^.]{0,80})$")
_CONF_RE = re.compile(
    r"proceedings|conference|workshop|symposium|\bconf\b|neurips|\bnips\b|icml|iclr|cvpr|"
    r"iccv|eccv|\bacl\b|emnlp|naacl|aaai|ijcai|sigir|\bkdd\b|\bchi\b|"
    r"neural information processing systems",
    re.IGNORECASE,
)
_JOURNAL_RE = re.compile(
    r"journal|transactions|letters|review|annals|nature|science|lancet|\bplos\b|bulletin|"
    r"quarterly|magazine|\bjama\b|\bbmj\b|\bnejm\b|\bcell\b",
    re.IGNORECASE,
)
_BOOK_RE = re.compile(r"\bpress\b|publisher|\bedition\b|\b\d+(?:st|nd|rd|th) ed\b|\bbooks?\b", re.I)


def _strip_markdown(text: str) -> str:
    return re.sub(r"[*_`]+", "", text)


def _volume_issue_pages(text: str) -> tuple[str | None, str | None, str | None]:
    volume = issue = pages = None
    m = re.search(r"\b(\d{1,4})\s*\((\d{1,4}(?:[-–]\d{1,4})?)\)", text)
    if m:
        volume, issue = m.group(1), m.group(2)
    m = re.search(r"\bvol(?:ume)?\.?\s*(\d{1,4})", text, re.IGNORECASE)
    if m:
        volume = m.group(1)
    m = re.search(r"\b(?:no|issue)\.?\s*(\d{1,4})", text, re.IGNORECASE)
    if m:
        issue = m.group(1)
    m = re.search(r"\bpp?\.?\s*([A-Za-z]?\d+\s*[-–—]+\s*[A-Za-z]?\d+|\d+)", text, re.IGNORECASE)
    if not m:  # the last range: "Physica B, 308-310, 431–433" has a volume range first
        ranges = list(re.finditer(r"[,:]\s*([A-Za-z]?\d{1,6}\s*[-–—]+\s*[A-Za-z]?\d{1,6})\b", text))
        m = ranges[-1] if ranges else None
    if m:
        pages = re.sub(r"\s*[-–—]+\s*", "-", m.group(1))
    if volume is None:  # APA: "Venue, 30, 5998–6008"
        m = re.search(r",\s*(\d{1,4})\s*,\s*(?:pp?\.?\s*)?[A-Za-z]?\d", text)
        if m:
            volume = m.group(1)
    return volume, issue, pages


def _venue_from(segment: str) -> str | None:
    seg = _strip_markdown(segment)
    seg = re.sub(r"^\s*(?:in|In)[:\s]+", "", seg)
    seg = re.split(
        r",\s*(?:vol|no|pp|p\.|\d)|\s+\d{1,4}\s*\(|;\s*\d|\bvol\.|\bpp\.", seg, maxsplit=1
    )[0]
    seg = _YEAR_RE.sub("", seg).strip(" .,;:()")
    return seg or None


def _infer_type(raw: str, venue: str | None, arxiv: bool) -> CitationType:
    v = venue or ""
    if arxiv and (not venue or "arxiv" in v.lower()):
        return CitationType.PREPRINT
    if re.search(r"thesis|dissertation", raw, re.IGNORECASE):
        return CitationType.THESIS
    if re.search(r"technical report|tech\. rep|white paper", raw, re.IGNORECASE):
        return CitationType.REPORT
    if _CONF_RE.search(v):
        return CitationType.PAPER_CONFERENCE
    if _JOURNAL_RE.search(v):
        return CitationType.ARTICLE_JOURNAL
    if _BOOK_RE.search(raw):
        return CitationType.BOOK
    if venue:
        return CitationType.ARTICLE_JOURNAL
    return CitationType.UNKNOWN


_BOUNDARY = ".,;:?!()[]\"“”'‘’"


def locate_title(text: str, title: str | None) -> re.Match[str] | None:
    """Find `title` inside `text` as a whole segment, ignoring case and punctuation: it must
    sit between punctuation, so "Attention is all you need for proteins" does not contain
    "Attention is all you need". Needs at least four words."""
    words = re.findall(r"\w+", title or "")
    if len(words) < 4:
        return None
    for m in re.finditer(r"\W+".join(map(re.escape, words)), text, re.IGNORECASE):
        before, after = text[: m.start()].rstrip(), text[m.end() :].lstrip()
        if (not before or before[-1] in _BOUNDARY) and (not after or after[0] in _BOUNDARY):
            return m
    return None


def parse_heuristic(raw: str, title_hint: str | None = None) -> ParsedReference:
    """`title_hint` is the title of a known record found inside `raw`; the reference is then
    split around it (used to recover from a failed parse)."""
    ids = extract_identifiers(raw)
    text = _LEAD_RE.sub("", raw.strip())
    bold = _BOLD_RE.search(text)
    italics = [m.group(1) for m in _ITALIC_RE.finditer(text.replace("**", "\x00"))]
    text = strip_identifiers(text)
    text = re.sub(r"\s*(?:Available (?:at|from)|Retrieved from|URL)\s*:?\s*$", "", text, flags=re.I)

    authors_part = title = venue = None
    rest = ""
    year: int | None = None
    confidence = 0.5

    quoted = _QUOTED_RE.search(text)
    paren_year = _YEAR_PAREN_RE.search(text)
    vancouver = _VANCOUVER_RE.match(text)
    hinted = locate_title(text, title_hint)
    # A quoted title follows the author list or the year (`Lee, K., “Title,”`). A quote that
    # follows a word is a phrase inside the title: `(2022). Introducing the “How to …” series.`
    if quoted and (vancouver or (paren_year and paren_year.end() < quoted.start())):
        before = text[: quoted.start()].rstrip()
        if before and before[-1].isalnum():
            quoted = None
    if hinted:
        authors_part = text[: hinted.start()]
        if paren_year and paren_year.end() <= hinted.start():
            authors_part = text[: paren_year.start()]
        title = hinted.group(0)
        rest = text[hinted.end() :].lstrip(' .,:;"”')
        confidence = 0.8
    elif bold:  # chatbot style: Authors (Year). **Title**. *Venue*.
        title = bold.group(1).strip(" .")
        authors_part = text[: text.find("**")]
        if paren_year and paren_year.start() < text.find("**"):
            authors_part = text[: paren_year.start()]
        rest = text[text.rfind("**") + 2 :]
        confidence = 0.7
    elif vancouver and not quoted and not paren_year:  # Smith JA, Doe B. Title. Journal. 2015;…
        authors_part = vancouver.group("authors")
        segments = [s.strip() for s in _SENT_SPLIT_RE.split(vancouver.group("rest")) if s.strip()]
        # The journal sits just before "2008;2(6)". A lowercase one ("animal", "eLife",
        # "npj …") does not start a new sentence, so it is still glued to the title.
        if len(segments) >= 2 and _YEAR_START_RE.match(segments[1]):
            glued = _LOWER_VENUE_RE.match(segments[0])
            if glued:
                segments[:1] = [glued.group("title"), glued.group("venue")]
        title = segments[0] if segments else None
        rest = ". ".join(segments[1:])
        confidence = 0.7
    elif quoted:  # IEEE / MLA / Chicago
        title = quoted.group(1).strip(" ,.")
        authors_part = text[: quoted.start()]
        rest = text[quoted.end() :]
        confidence = 0.75
    elif paren_year and paren_year.start() < len(text) * 0.6:  # APA / Harvard
        authors_part = text[: paren_year.start()]
        after = text[paren_year.end() :].lstrip(" .,:")
        m = re.match(r"(.+?[.?!])(?:\s+|$)(.*)$", after)
        if m:
            title, rest = m.group(1).strip(), m.group(2)
            if title.endswith("."):
                title = title[:-1]
        else:
            title = after
        confidence = 0.75
    else:  # Vancouver / generic sentence-split
        segments = [s.strip() for s in _SENT_SPLIT_RE.split(text) if s.strip()]
        if len(segments) >= 2:
            authors_part, title = segments[0], segments[1]
            rest = ". ".join(segments[2:])
            m = re.match(r"^(.*?)[,.]?\s*\(?((?:1[6-9]|20)\d{2})\)?$", authors_part)
            if m and m.group(1):
                authors_part = m.group(1)
            confidence = 0.55 if len(segments) >= 3 else 0.4
        else:
            title = text
            confidence = 0.25

    if paren_year:
        year = int(paren_year.group("year"))
    else:
        years = [int(y) for y in _YEAR_RE.findall(text)]
        year = years[-1] if years else None

    authors, truncated = split_author_list(_strip_markdown(authors_part or ""))
    if authors_part and len(authors_part) > 300:  # authors segment swallowed everything
        authors, confidence = [], min(confidence, 0.3)

    if italics:
        italic_venue = next((i for i in italics if title and i.strip(" .") != title), None)
        if italic_venue:
            venue = italic_venue.strip(" .,")
    if not venue and rest:
        venue = _venue_from(rest)
    volume, issue, pages = _volume_issue_pages(rest or text)

    if title:
        title = _strip_markdown(title).strip(' .,"“”')
        if _AUTHOR_LIST_RE.search(title + ". "):
            confidence = min(confidence, 0.3)
    ctype = _infer_type(raw, venue, bool(ids.arxiv_id))
    publisher = None
    if ctype == CitationType.BOOK and venue and _BOOK_RE.search(venue):
        publisher, venue = venue, None
    return ParsedReference(
        raw=raw.strip(),
        authors=authors,
        authors_truncated=truncated,
        title=title or None,
        container_title=venue,
        year=year,
        volume=volume,
        issue=issue,
        pages=pages,
        publisher=publisher,
        type=ctype,
        ids=ids,
        parse_method="heuristic",
        parse_confidence=confidence if title else 0.2,
    )
