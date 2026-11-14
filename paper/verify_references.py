"""Run CiteGuard on this paper's own bibliography.

    cd backend && .venv/bin/python ../paper/verify_references.py

Writes paper/generated/reference_check.tex (a table included in the appendix) and prints
one line per entry. A citation-checking paper should pass its own check."""

from __future__ import annotations

import asyncio
from pathlib import Path

from citeguard.config import get_settings
from citeguard.domain.models import CheckOptions
from citeguard.engine import Engine
from citeguard.observability.logging import configure_logging

HERE = Path(__file__).resolve().parent
BIB = HERE / "references.bib"
OUT = HERE / "generated" / "reference_check.tex"


def tex_escape(s: str) -> str:
    return s.replace("&", r"\&").replace("_", r"\_").replace("%", r"\%").replace("#", r"\#")


async def main() -> None:
    configure_logging("WARNING")
    options = CheckOptions(use_llm=False, explain=False, suggest_alternatives=False)
    async with Engine(get_settings()) as engine:
        report = await engine.check("bibtex", BIB.read_text(), options=options)
    rows = []
    for c in report.citations:
        key = c.reference.key or c.reference.raw[:30]
        source = c.best_match.record.source if c.best_match else "--"
        conf = f"{c.confidence:.2f}"
        codes = ", ".join(d.code.value for d in c.discrepancies) or "--"
        print(f"{key:28} {c.verdict.value:22} {conf:5} {source:16} {codes}")
        rows.append(
            rf"\texttt{{{tex_escape(key)}}} & {tex_escape(c.verdict.value.replace('_', ' ').lower())}"
            rf" & {conf} & {tex_escape(source)} \\"
        )
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(rows) + "\n")
    s = report.summary
    print(f"\n{len(report.citations)} entries; verdicts: {s.by_verdict}")


if __name__ == "__main__":
    asyncio.run(main())
