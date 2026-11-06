"""`citeguard` command-line interface. Runs the engine in-process (no server needed)."""

from __future__ import annotations

import asyncio
import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn
from rich.table import Table
from rich.text import Text

from citeguard.config import get_settings
from citeguard.domain.models import CheckOptions, CheckReport, CitationResult, InputKind, Verdict
from citeguard.engine import Engine
from citeguard.explain.templates import SOURCE_NAMES
from citeguard.ingest.documents import sniff_kind
from citeguard.observability.logging import configure_logging

app = typer.Typer(
    name="citeguard",
    help="Detect fabricated and inaccurate citations, explain why, and suggest real alternatives.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
err = Console(stderr=True)

VERDICT_STYLE = {
    Verdict.VERIFIED: ("✔ VERIFIED", "green"),
    Verdict.VERIFIED_WITH_ERRORS: ("✎ HAS ERRORS", "yellow"),
    Verdict.MISATTRIBUTED: ("⚠ MISATTRIBUTED", "dark_orange"),
    Verdict.FABRICATED: ("✘ FABRICATED", "bold red"),
    Verdict.UNVERIFIABLE: ("? UNVERIFIABLE", "grey62"),
}


class OutputFormat(StrEnum):
    table = "table"
    json = "json"
    markdown = "markdown"


class Style(StrEnum):
    apa = "apa"
    ieee = "ieee"
    bibtex = "bibtex"


def _read_input(
    path: Path | None, text: str | None, citation: str | None
) -> tuple[InputKind, str | bytes]:
    if citation:
        return "citation", citation
    if text:
        return "text", text
    if path is None or str(path) == "-":
        data = sys.stdin.buffer.read()
        return sniff_kind(data), data  # type: ignore[return-value]
    if not path.exists():
        raise typer.BadParameter(f"{path} does not exist")
    data = path.read_bytes()
    kind = sniff_kind(data, path.name)
    return kind, data  # type: ignore[return-value]


def _verdict_text(v: Verdict) -> Text:
    label, style = VERDICT_STYLE[v]
    return Text(label, style=style)


def _title(r: CitationResult, width: int = 70) -> str:
    t = r.reference.title or r.reference.raw
    return t if len(t) <= width else t[: width - 1] + "…"


def render_table(report: CheckReport) -> None:
    table = Table(title="Citation check", show_lines=False, expand=True)
    table.add_column("#", justify="right", width=3)
    table.add_column("Verdict", no_wrap=True)
    table.add_column("Conf.", justify="right", width=5)
    table.add_column("Citation", ratio=3)
    table.add_column("Finding", ratio=4)
    for r in report.citations:
        headline = r.explanation.headline if r.explanation else ""
        table.add_row(
            str(r.index + 1),
            _verdict_text(r.verdict),
            f"{r.confidence:.2f}",
            _title(r),
            headline,
        )
    console.print(table)


def render_details(report: CheckReport, style: str, show_all: bool) -> None:
    for r in report.citations:
        if r.verdict == Verdict.VERIFIED and not show_all:
            continue
        label, color = VERDICT_STYLE[r.verdict]
        body = Text()
        body.append(r.reference.raw.strip() + "\n\n", style="italic")
        if r.explanation:
            body.append(r.explanation.headline + "\n", style="bold")
            ev = {e.id: e for e in r.evidence}
            for i, reason in enumerate(r.explanation.reasons, 1):
                body.append(f"  {i}. {reason.text}")
                links = [
                    f"{SOURCE_NAMES.get(ev[e].source, ev[e].source)}"
                    for e in reason.evidence_ids
                    if e in ev
                ]
                if links:
                    body.append(f"  [{', '.join(dict.fromkeys(links))}]", style="dim")
                body.append("\n")
            body.append("→ " + r.explanation.recommendation + "\n", style="cyan")
        for s in r.suggestions:
            if s.kind == "correction":
                body.append("\nCorrected citation:\n", style="bold green")
                body.append(
                    "  " + s.formatted.get(style, next(iter(s.formatted.values()), "")) + "\n"
                )
        alts = [s for s in r.suggestions if s.kind == "alternative"]
        if alts:
            body.append(
                "\nReal alternatives (verify relevance before citing):\n", style="bold green"
            )
            for i, s in enumerate(alts, 1):
                body.append(f"  {i}. " + s.formatted.get(style, "") + "\n")
                if s.relevance_note:
                    body.append(f"     {s.relevance_note}\n", style="dim")
        if r.flags:
            body.append("\nFlags: " + ", ".join(f.value for f in r.flags) + "\n", style="magenta")
        console.print(
            Panel(
                body,
                title=f"[{color}]#{r.index + 1} {label}[/] · confidence {r.confidence:.2f}",
                border_style=color,
            )
        )


def render_summary(report: CheckReport) -> None:
    s = report.summary
    parts = [f"{s.total} citations"]
    for v in Verdict:
        n = s.by_verdict.get(v.value, 0)
        if n:
            label, color = VERDICT_STYLE[v]
            parts.append(f"[{color}]{n} {label.split(' ', 1)[1].lower()}[/]")
    console.print(" · ".join(parts))
    u = s.llm_usage
    llm = (
        f"LLM: {u.calls} calls, {u.input_tokens + u.output_tokens} tokens"
        if u.calls
        else "LLM: off"
    )
    console.print(f"[dim]{llm} · explanations: {s.llm_mode}[/]")
    if s.sources_unhealthy:
        console.print(f"[yellow]Degraded sources: {', '.join(s.sources_unhealthy)}[/]")
    for w in report.warnings:
        console.print(f"[yellow]warning:[/] {w}")


def render_markdown(report: CheckReport, style: str) -> str:
    lines = ["# Citation check", ""]
    s = report.summary
    lines.append(
        f"**{s.total} citations** · "
        + " · ".join(f"{v}: {n}" for v, n in s.by_verdict.items() if n)
    )
    lines.append("")
    for r in report.citations:
        lines.append(f"## {r.index + 1}. {r.verdict.value} (confidence {r.confidence:.2f})")
        lines.append(f"> {r.reference.raw}")
        if r.explanation:
            lines += ["", f"**{r.explanation.headline}**", ""]
            lines += [f"- {x.text}" for x in r.explanation.reasons]
            lines += ["", f"_{r.explanation.recommendation}_"]
        for sug in r.suggestions:
            prefix = "Corrected" if sug.kind == "correction" else "Alternative"
            lines.append(f"- **{prefix}:** {sug.formatted.get(style, '')}")
        lines.append("")
    return "\n".join(lines)


@app.command()
def check(
    path: Annotated[
        Path | None,
        typer.Argument(help="File to check (.pdf, .docx, .bib, .tex, .txt, .md) or '-'"),
    ] = None,
    text: Annotated[
        str | None, typer.Option("--text", "-t", help="Check text given inline")
    ] = None,
    citation: Annotated[
        str | None, typer.Option("--citation", "-c", help="Check a single citation string")
    ] = None,
    output_format: Annotated[OutputFormat, typer.Option("--format", "-f")] = OutputFormat.table,
    style: Annotated[
        Style, typer.Option("--style", "-s", help="Style for suggestions")
    ] = Style.apa,
    no_llm: Annotated[
        bool, typer.Option("--no-llm", help="Deterministic mode, no Groq calls")
    ] = False,
    no_alternatives: Annotated[bool, typer.Option("--no-alternatives")] = False,
    all_details: Annotated[
        bool, typer.Option("--all", help="Show details for verified ones too")
    ] = False,
    fail_on: Annotated[
        str | None,
        typer.Option(help="Comma-separated verdicts that make the exit code non-zero"),
    ] = None,
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Write report to file")
    ] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Check citations for fabrication, misattribution and errors."""
    settings = get_settings()
    configure_logging("DEBUG" if verbose else "WARNING")
    kind, content = _read_input(path, text, citation)
    options = CheckOptions(
        use_llm=not no_llm,
        suggest_alternatives=not no_alternatives,
        styles=["apa", "ieee", "bibtex"],
    )
    if not no_llm and not settings.llm_available:
        err.print("[dim]GROQ_API_KEY not set: running in deterministic mode (no LLM).[/]")

    report = asyncio.run(_run(kind, content, options, interactive=output_format == "table"))

    if output_format == OutputFormat.json:
        payload = report.model_dump_json(indent=2)
        (output.write_text(payload) if output else console.print_json(payload))
    elif output_format == OutputFormat.markdown:
        md = render_markdown(report, style.value)
        (output.write_text(md) if output else console.print(md, markup=False, highlight=False))
    else:
        render_table(report)
        render_details(report, style.value, all_details)
        render_summary(report)
        if output:
            output.write_text(report.model_dump_json(indent=2))

    if fail_on:
        wanted = {v.strip().upper() for v in fail_on.split(",")}
        if any(r.verdict.value in wanted for r in report.citations):
            raise typer.Exit(code=1)


async def _run(
    kind: InputKind, content: str | bytes, options: CheckOptions, interactive: bool
) -> CheckReport:
    async with Engine() as engine:
        if not interactive:
            return await engine.check(kind, content, options=options)
        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            console=err,
            transient=True,
        ) as progress:
            task = progress.add_task("Parsing references…", total=None)

            async def on_event(event: str, payload: dict[str, Any]) -> None:
                if event == "check.parsed":
                    progress.update(task, total=payload["count"], description="Verifying…")
                elif event == "citation.verified":
                    progress.advance(task)
                elif event == "citation.enriched":
                    progress.update(task, description="Explaining & suggesting…")

            return await engine.check(kind, content, options=options, on_event=on_event)


@app.command()
def sources() -> None:
    """Probe every enabled scholarly source with a known DOI."""

    async def probe() -> None:
        async with Engine() as engine:
            assert engine.sources is not None
            table = Table(title="Source health")
            table.add_column("Source")
            table.add_column("Status")
            table.add_column("Latency")
            from citeguard.sources.base import SearchQuery

            q = SearchQuery(title="Deep learning", author="LeCun", year=2015)
            if engine.sources.doi:
                r = await engine.sources.doi.registered("10.1038/nature14539")
                table.add_row("doi.org", r.status.value, f"{r.latency_ms} ms")
            for s in engine.sources.by_name.values():
                r = await s.search(q, 1)
                table.add_row(s.display_name, r.status.value, f"{r.latency_ms} ms")
            console.print(table)

    configure_logging("WARNING")
    asyncio.run(probe())


@app.command()
def version() -> None:
    """Print the version."""
    console.print(get_settings().app_version)


@app.command()
def serve(
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option()] = 8000,
    reload: Annotated[bool, typer.Option()] = False,
) -> None:
    """Run the HTTP API (inline job backend unless JOB_BACKEND=arq)."""
    import uvicorn

    uvicorn.run("citeguard.api.app:create_app", factory=True, host=host, port=port, reload=reload)


@app.command("create-key")
def create_key(
    name: Annotated[str, typer.Option(help="Who or what the key is for")],
    rate_limit: Annotated[int, typer.Option(help="Checks per minute")] = 30,
) -> None:
    """Create an API key (printed once; only its hash is stored)."""
    from citeguard.db.repo import Repository
    from citeguard.db.session import create_all, make_engine, make_sessionmaker

    async def run() -> str:
        settings = get_settings()
        db = make_engine(settings.database_url)
        await create_all(db)
        _, raw = await Repository(make_sessionmaker(db)).create_api_key(name, rate_limit)
        await db.dispose()
        return raw

    raw = asyncio.run(run())
    console.print(f"[bold]API key for {name}:[/] {raw}")
    console.print("[dim]Store it now: it cannot be shown again.[/]")


if __name__ == "__main__":
    app()
