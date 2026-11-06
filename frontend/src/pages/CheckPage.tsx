import { ArrowDownWideNarrow, Download, FileCode2, FileSpreadsheet, FileText, Globe, ListOrdered, Radio, Search, Sparkles } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import { useLiveCheck } from "../api/hooks";
import type { CitationSummary, ExportFormat, Verdict } from "../api/types";
import { CitationDrawer } from "../components/CitationDrawer";
import { ErrorNote, Segmented, Spinner, VerdictBadge, cx } from "../components/ui";
import { settings } from "../lib/settings";
import { FLAG_LABELS, VERDICTS, VERDICT_ORDER, confidenceLabel } from "../lib/verdicts";

const KIND_LABEL: Record<string, string> = {
  text: "Pasted text",
  bibtex: "BibTeX",
  citation: "Single citation",
  pdf: "PDF",
  docx: "Word document",
  latex: "LaTeX",
};

const EXPORTS: { format: ExportFormat; label: string; icon: typeof FileText }[] = [
  { format: "html", label: "Report (HTML)", icon: Globe },
  { format: "bib", label: "Corrected .bib", icon: FileCode2 },
  { format: "csv", label: "CSV", icon: FileSpreadsheet },
  { format: "md", label: "Markdown", icon: FileText },
  { format: "json", label: "JSON", icon: FileCode2 },
];

function SummaryBar({
  counts,
  total,
  filter,
  onFilter,
}: {
  counts: Record<string, number>;
  total: number;
  filter: Verdict | null;
  onFilter: (v: Verdict | null) => void;
}) {
  return (
    <div className="space-y-3">
      <div className="flex h-2 overflow-hidden rounded-full bg-ink-100 dark:bg-ink-800" aria-hidden>
        {VERDICT_ORDER.map((v) =>
          counts[v] ? (
            <div key={v} className={VERDICTS[v].dot} style={{ width: `${(100 * (counts[v] ?? 0)) / Math.max(total, 1)}%` }} />
          ) : null,
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => onFilter(null)}
          className={cx("rounded-full px-3 py-1 text-sm font-medium ring-1 ring-inset", filter === null ? "bg-ink-900 text-white ring-ink-900 dark:bg-white dark:text-ink-900" : "ring-ink-200 hover:bg-ink-100 dark:ring-ink-700 dark:hover:bg-ink-800")}
        >
          All {total}
        </button>
        {VERDICT_ORDER.map((v) => {
          const n = counts[v] ?? 0;
          if (!n) return null;
          return (
            <button
              key={v}
              type="button"
              onClick={() => onFilter(filter === v ? null : v)}
              aria-pressed={filter === v}
              className={cx("inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-medium ring-1 ring-inset transition", VERDICTS[v].badge, filter === v && "ring-2")}
            >
              <span className={cx("size-1.5 rounded-full", VERDICTS[v].dot)} />
              {n} {VERDICTS[v].label.toLowerCase()}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function CitationRow({ c, onOpen }: { c: CitationSummary; onOpen: () => void }) {
  return (
    <li>
      <button type="button" onClick={onOpen} className="flex w-full gap-4 px-4 py-3.5 text-left transition hover:bg-ink-50 dark:hover:bg-ink-800/50">
        <span className="w-6 shrink-0 pt-0.5 text-right font-mono text-xs text-ink-400">{c.index + 1}</span>
        <span className="min-w-0 flex-1 space-y-1">
          <span className="flex flex-wrap items-center gap-2">
            <VerdictBadge verdict={c.verdict} />
            {c.explanation_mode === "llm" && (
              <span className="inline-flex items-center gap-1 text-[11px] text-ink-500" title="Explanation written by the LLM and checked against evidence">
                <Sparkles className="size-3" /> LLM
              </span>
            )}
            {c.flags.filter((f) => f !== "LLM_ADJUDICATED").map((f) => (
              <span key={f} className={cx("rounded px-1.5 py-0.5 text-[11px] font-medium", f === "RETRACTED" || f === "CLAIM_NOT_SUPPORTED" ? "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200" : "bg-ink-100 text-ink-600 dark:bg-ink-800 dark:text-ink-300")}>
                {FLAG_LABELS[f] ?? f}
              </span>
            ))}
            {c.claim_support === "PARTIAL" && (
              <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[11px] font-medium text-amber-800 dark:bg-amber-950/50 dark:text-amber-300">
                Claim partly supported
              </span>
            )}
          </span>
          <span className="block truncate font-medium">{c.title ?? c.raw}</span>
          {c.headline && <span className="line-clamp-2 block text-sm text-ink-600 dark:text-ink-400">{c.headline}</span>}
        </span>
        <span className="hidden shrink-0 text-right text-xs text-ink-500 sm:block">
          {confidenceLabel(c.confidence)}
          <br />
          {c.has_correction && <span className="text-emerald-700 dark:text-emerald-400">fix available</span>}
          {c.alternatives > 0 && <span className="text-emerald-700 dark:text-emerald-400">{c.alternatives} alternatives</span>}
        </span>
      </button>
    </li>
  );
}

export function CheckPage() {
  const { id = "" } = useParams();
  const { data: check, isLoading, error, live } = useLiveCheck(id);
  const [filter, setFilter] = useState<Verdict | null>(null);
  const [order, setOrder] = useState<"severity" | "document">("severity");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const close = useCallback(() => setOpen(null), []);

  const counts = useMemo(() => {
    const out: Record<string, number> = {};
    for (const c of check?.citations ?? []) out[c.verdict] = (out[c.verdict] ?? 0) + 1;
    return out;
  }, [check]);

  const visible = useMemo(() => {
    let list = [...(check?.citations ?? [])];
    if (filter) list = list.filter((c) => c.verdict === filter);
    const q = query.trim().toLowerCase();
    if (q) list = list.filter((c) => (c.title ?? c.raw).toLowerCase().includes(q) || c.raw.toLowerCase().includes(q));
    if (order === "severity") list.sort((a, b) => VERDICTS[a.verdict].severity - VERDICTS[b.verdict].severity || a.index - b.index);
    return list;
  }, [check, filter, query, order]);

  if (isLoading) return <div className="flex justify-center py-20"><Spinner className="size-6" /></div>;
  if (error || !check) return <ErrorNote>{(error as Error)?.message ?? "Check not found."}</ErrorNote>;

  const running = check.status === "queued" || check.status === "running";
  const total = Math.max(check.progress_total, check.citations.length);
  const pct = total ? Math.round((100 * check.progress_done) / total) : 0;
  const unsupported = check.citations.filter(
    (c) => (c.verdict === "VERIFIED" || c.verdict === "UNVERIFIABLE") && c.flags.includes("CLAIM_NOT_SUPPORTED"),
  ).length;
  const problems =
    (counts.FABRICATED ?? 0) + (counts.MISATTRIBUTED ?? 0) + (counts.VERIFIED_WITH_ERRORS ?? 0) + unsupported;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Link to="/history" className="text-xs text-ink-500 hover:underline">← All checks</Link>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">{check.filename ?? KIND_LABEL[check.input_kind] ?? "Check"}</h1>
          <p className="mt-1 flex items-center gap-2 text-sm text-ink-500">
            {new Date(check.created_at).toLocaleString()}
            {running && (
              <span className="inline-flex items-center gap-1 text-brand-600 dark:text-brand-500">
                <Radio className={cx("size-3.5", live && "animate-pulse")} /> {live ? "live" : "updating"}
              </span>
            )}
          </p>
        </div>
        {check.status === "completed" && (
          <div className="flex flex-wrap gap-2">
            {EXPORTS.map(({ format, label, icon: Icon }) => (
              <button
                key={format}
                type="button"
                className="btn-outline text-xs"
                onClick={() => api.download(check.id, format, settings.getStyle()).catch((e: Error) => setExportError(e.message))}
              >
                {format === "html" ? <Icon className="size-3.5" /> : <Download className="size-3.5" />}
                {label}
              </button>
            ))}
          </div>
        )}
      </div>

      {exportError && <ErrorNote>{exportError}</ErrorNote>}
      {check.status === "failed" && <ErrorNote>This check failed: {check.error ?? "unknown error"}</ErrorNote>}
      {check.warnings.length > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
          {check.warnings.map((w) => <p key={w}>{w}</p>)}
        </div>
      )}

      <div className="card space-y-4 p-5">
        {running ? (
          <div>
            <div className="mb-2 flex justify-between text-sm">
              <span className="font-medium">
                {check.status === "queued" ? "Queued…" : total ? `Verifying ${check.progress_done} of ${total}` : "Finding references…"}
              </span>
              <span className="text-ink-500">{pct}%</span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-ink-100 dark:bg-ink-800">
              <div className="h-full bg-brand-500 transition-all" style={{ width: `${pct}%` }} />
            </div>
          </div>
        ) : (
          <p className="text-lg">
            <span className="font-semibold">{check.citations.length} citation{check.citations.length === 1 ? "" : "s"} checked.</span>{" "}
            {problems ? (
              <span className="text-ink-600 dark:text-ink-300">{problems} need attention.</span>
            ) : (
              <span className="text-emerald-700 dark:text-emerald-400">No problems found.</span>
            )}
          </p>
        )}
        {check.citations.length > 0 && <SummaryBar counts={counts} total={check.citations.length} filter={filter} onFilter={setFilter} />}
      </div>

      {check.citations.length > 0 && (
        <div className="card overflow-hidden">
          <div className="flex flex-wrap items-center gap-3 border-b border-ink-200 px-4 py-3 dark:border-ink-800">
            <label className="relative min-w-48 flex-1">
              <Search className="pointer-events-none absolute top-2.5 left-2.5 size-4 text-ink-400" />
              <input className="input pl-8" placeholder="Search citations" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search citations" />
            </label>
            <Segmented<"severity" | "document">
              ariaLabel="Order"
              value={order}
              onChange={setOrder}
              options={[
                { value: "severity", label: <><ArrowDownWideNarrow className="size-4" />Most severe</> },
                { value: "document", label: <><ListOrdered className="size-4" />Document order</> },
              ]}
            />
          </div>
          {visible.length ? (
            <ul className="divide-y divide-ink-100 dark:divide-ink-800">
              {visible.map((c) => <CitationRow key={c.index} c={c} onOpen={() => setOpen(c.index)} />)}
            </ul>
          ) : (
            <p className="px-4 py-10 text-center text-sm text-ink-500">No citations match this filter.</p>
          )}
        </div>
      )}

      {!running && check.citations.length === 0 && check.status === "completed" && (
        <p className="text-center text-ink-500">No references were found in this input.</p>
      )}

      <CitationDrawer checkId={check.id} index={open} onClose={close} />
    </div>
  );
}
