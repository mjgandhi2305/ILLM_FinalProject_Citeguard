"""Turn eval/runs/*/summary.json into LaTeX tables and macros for the paper.

    python3 paper/make_results.py

Writes paper/generated/{test3_table.tex, heldout_table.tex, dev_table.tex, llm_only_breakdown.tex,
macros.tex}. No number in the paper's result tables is typed by hand."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "eval" / "runs"
OUT = Path(__file__).resolve().parent / "generated"
FAKE = ("FABRICATED", "MISATTRIBUTED")
METRICS = ("Acc", "MacroF", "F", "Rec", "Prec", "FPR", "CFPR", "ECE", "Tok", "LatP", "LatQ")


def load(name: str) -> dict | None:
    p = RUNS / name / "summary.json"
    return json.loads(p.read_text()) if p.exists() else None


def correct_fpr(s: dict) -> float:
    """Share of perfectly correct citations (gold VERIFIED) called fake."""
    row = s["confusion"]["VERIFIED"]
    n = sum(row.values())
    return sum(row[k] for k in FAKE) / n if n else 0.0


def f3(x: float | None) -> str:
    return "--" if x is None else f"{x:.3f}"


def pct(x: float) -> str:
    return f"{100 * x:.1f}"


def row(label: str, s: dict | None, *, bold: bool = False, tokens: str | None = None) -> str:
    if s is None:
        return rf"{label} & \multicolumn{{8}}{{c}}{{(not run)}} \\"
    f = s["fake_detection"]
    has_fake = f["precision"] > 0 or f["recall"] > 0
    cells = [
        f3(s["accuracy"]),
        f3(s["macro_f1"]),
        f3(f["precision"]) if has_fake else "--",
        f3(f["recall"]),
        f3(f["f1"]),
        pct(correct_fpr(s)),
        pct(f["false_positive_rate_on_real"]),
        tokens or f"{s['llm_tokens_per_citation']:.0f}",
    ]
    if bold:
        cells = [rf"\textbf{{{c}}}" for c in cells]
    return f"{label} & " + " & ".join(cells) + r" \\"


def bold_best(lines: list[str]) -> list[str]:
    """Bold the best value of each metric column (higher is better, except the two FPRs)."""
    rows = [ln for ln in lines if "&" in ln and "multicolumn" not in ln]
    cells = [ln.rstrip(" \\").split(" & ") for ln in rows]
    best: dict[int, float] = {}
    for col in range(1, 8):
        vals = [float(c[col]) for c in cells if c[col] not in ("--", "??")]
        if vals:
            best[col] = min(vals) if col in (6, 7) else max(vals)
    out = []
    for ln in lines:
        if ln not in rows:
            out.append(ln)
            continue
        c = ln.rstrip(" \\").split(" & ")
        for col, b in best.items():
            if c[col] not in ("--", "??") and float(c[col]) == b:
                c[col] = rf"\textbf{{{c[col]}}}"
        out.append(" & ".join(c) + r" \\")
    return out


TEST3 = [
    ("Offline heuristics only", "citebench_test3-heuristics"),
    (r"DOI lookup only~\citep{kim2026hallmark}", "citebench_test3-doi_only"),
    (r"LLM-only, \texttt{gpt-oss-20b}", "citebench_test3-llm_only-gpt-oss-20b"),
    (r"LLM-only, \texttt{qwen3.8-27b}", "citebench_test3-llm_only-qwen3.8-27b"),
    (r"LLM-only, \texttt{gpt-oss-120b}", "citebench_test3-llm_only-gpt-oss-120b"),
    ("CiteGuard, exact matching only", "citebench_test3-exact"),
    ("CiteGuard, deterministic (\\texttt{no\\_llm})", "citebench_test3-no_llm"),
    ("CiteGuard, full (Groq LLM)", "citebench_test3-full"),
]


def main() -> None:
    OUT.mkdir(exist_ok=True)
    macros: list[str] = []

    lines = []
    for i, (label, name) in enumerate(TEST3):
        if i in (2, 5):
            lines.append(r"\midrule")
        lines.append(row(label, load(name)))
    (OUT / "test3_table.tex").write_text("\n".join(bold_best(lines)) + "\n")

    held = [
        ("\\texttt{test} (seed 23)", "citebench_test-no_llm-prefix"),
        ("\\texttt{test2} (seed 41)", "citebench_test2-no_llm-prefix"),
        ("\\texttt{test3} (seed 59)", "citebench_test3-no_llm"),
    ]
    lines = []
    for label, name in held:
        s = load(name)
        if s is None:
            continue
        f = s["fake_detection"]
        lines.append(
            f"{label} & {f3(s['accuracy'])} & {f3(s['macro_f1'])} & {f3(f['precision'])} & "
            f"{f3(f['recall'])} & {pct(f['false_positive_rate_on_real'])} & {f3(s['ece'])} & "
            + (
                "cached \\\\"
                if "test3" in name  # scored after the exact-matching run had filled the cache
                else f"{s['latency_ms']['p50'] / 1000:.1f} / {s['latency_ms']['p95'] / 1000:.0f} \\\\"
            )
        )
    (OUT / "heldout_table.tex").write_text("\n".join(lines) + "\n")

    dev = [
        ("Offline heuristics only", "citebench_dev-heuristics"),
        ("+ retrieval, exact matching", "citebench_dev-exact"),
        ("+ fuzzy linkage and full rules (\\texttt{no\\_llm})", "citebench_dev-no_llm-authors"),
        ("+ Groq LLM (\\texttt{full})", "citebench_dev-full"),
        ("LLM-only, \\texttt{gpt-oss-120b}", "citebench_dev-llm_only"),
    ]
    # The dev full run was re-scored from the LLM cache, so its token count reads 0.
    lines = [
        row(label, load(name), tokens="cached" if name.endswith("-full") else None)
        for label, name in dev
    ]
    lines.insert(4, r"\midrule")
    (OUT / "dev_table.tex").write_text("\n".join(lines) + "\n")

    # How each LLM-only baseline answered, per gold group, on test3.
    groups = [
        ("Correct", ("none",)),
        ("Real w/ errors", ("year_shift", "venue_swap", "bogus_doi")),
        ("Misattributed", ("author_swap", "wrong_doi")),
        ("Fabricated", ("borrowed_doi", "fabricated")),
    ]
    breakdown: dict[str, dict[str, list[int]]] = {}
    for model in ("gpt-oss-20b", "qwen3.8-27b", "gpt-oss-120b"):
        p = RUNS / f"citebench_test3-llm_only-{model}" / "predictions.jsonl"
        if not p.exists():
            continue
        rows = [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
        breakdown[model] = {}
        for gname, perts in groups:
            g = [r for r in rows if (r.get("perturbation") or "none") in perts]
            exists = sum(r["pred"] == "VERIFIED" for r in g)
            fake = sum(r["pred"] in FAKE for r in g)
            breakdown[model][gname] = [len(g), exists, fake, len(g) - exists - fake]
    lines = []
    for gname, _ in groups:
        cells = []
        for model in breakdown:
            n, ex, fk, un = breakdown[model][gname]
            cells += [str(ex), str(fk), str(un)]
        n = next(iter(breakdown.values()))[gname][0] if breakdown else 0
        lines.append(f"{gname} ({n}) & " + " & ".join(cells) + r" \\")
    (OUT / "llm_only_breakdown.tex").write_text("\n".join(lines) + "\n")
    (OUT / "llm_only_breakdown.json").write_text(json.dumps(breakdown, indent=2))

    # Headline macros used in the abstract and text.
    def mac(name: str, value: str) -> None:
        macros.append(rf"\newcommand{{\{name}}}{{{value}}}")

    names = {
        "Heur": "citebench_test3-heuristics",
        "Doi": "citebench_test3-doi_only",
        "LlmTwenty": "citebench_test3-llm_only-gpt-oss-20b",
        "LlmQwen": "citebench_test3-llm_only-qwen3.8-27b",
        "LlmBig": "citebench_test3-llm_only-gpt-oss-120b",
        "Exact": "citebench_test3-exact",
        "NoLlm": "citebench_test3-no_llm",
        "Full": "citebench_test3-full",
    }
    for key, name in names.items():
        s = load(name)
        if s is None:  # run not finished: keep the paper compilable
            for m in METRICS:
                mac(f"{key}{m}", "??")
            continue
        f = s["fake_detection"]
        mac(f"{key}Acc", f3(s["accuracy"]))
        mac(f"{key}MacroF", f3(s["macro_f1"]))
        mac(f"{key}F", f3(f["f1"]))
        mac(f"{key}Rec", f3(f["recall"]))
        mac(f"{key}Prec", f3(f["precision"]))
        mac(f"{key}FPR", pct(f["false_positive_rate_on_real"]))
        mac(f"{key}CFPR", pct(correct_fpr(s)))
        mac(f"{key}ECE", f3(s["ece"]))
        mac(f"{key}Tok", f"{s['llm_tokens_per_citation']:.0f}")
        mac(f"{key}LatP", f"{s['latency_ms']['p50'] / 1000:.1f}")
        mac(f"{key}LatQ", f"{s['latency_ms']['p95'] / 1000:.0f}")
    (OUT / "macros.tex").write_text("\n".join(macros) + "\n")
    print("wrote", ", ".join(sorted(p.name for p in OUT.iterdir())))


if __name__ == "__main__":
    main()
