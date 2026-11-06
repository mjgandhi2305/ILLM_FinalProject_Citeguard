"""LaTeX ingestion: `thebibliography` / `\\bibitem` entries plus `\\cite{key}` contexts.
(A project's `.bib` file is handled by the BibTeX ingestor; this covers inline bibliographies.)"""

from __future__ import annotations

import re

from citeguard.domain.models import ParsedReference
from citeguard.match.normalize import latex_to_text
from citeguard.parse.heuristic import parse_heuristic

_BIBITEM_RE = re.compile(r"\\bibitem(?:\[[^\]]*\])?\{([^}]+)\}")
_CITE_RE = re.compile(
    r"\\(?:cite|citep|citet|parencite|textcite|autocite)\*?(?:\[[^\]]*\])*\{([^}]+)\}"
)
_ENV_RE = re.compile(r"\\begin\{thebibliography\}(?:\{[^}]*\})?(.*?)\\end\{thebibliography\}", re.S)
_COMMENT_RE = re.compile(r"(?<!\\)%.*$", re.M)


def _contexts(body: str) -> dict[str, list[str]]:
    body = _COMMENT_RE.sub("", body)
    sentences = re.split(r"(?<=[.!?])\s+", " ".join(body.split()))
    out: dict[str, list[str]] = {}
    for sent in sentences:
        for m in _CITE_RE.finditer(sent):
            clean = latex_to_text(_CITE_RE.sub("[*]", sent)).strip()
            for key in m.group(1).split(","):
                out.setdefault(key.strip(), []).append(clean)
    return {k: list(dict.fromkeys(v))[:3] for k, v in out.items()}


def parse_latex(text: str) -> tuple[list[ParsedReference], list[str]]:
    env = _ENV_RE.search(text)
    if not env:
        return [], ["No thebibliography environment found; checking the text as plain references"]
    block = env.group(1)
    body = text[: env.start()]
    contexts = _contexts(body)
    items = list(_BIBITEM_RE.finditer(block))
    refs = []
    for i, m in enumerate(items):
        end = items[i + 1].start() if i + 1 < len(items) else len(block)
        raw_tex = " ".join(_COMMENT_RE.sub("", block[m.end() : end]).split())
        raw_tex = re.sub(r"\\newblock\s*", " ", raw_tex)
        raw = latex_to_text(raw_tex).strip()
        ref = parse_heuristic(raw)
        ref.key = m.group(1).strip()
        ref.contexts = contexts.get(ref.key, [])
        refs.append(ref)
    return refs, []
