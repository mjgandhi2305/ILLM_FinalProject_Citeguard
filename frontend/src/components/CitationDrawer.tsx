import { useMutation } from "@tanstack/react-query";
import { ChevronDown, ExternalLink, Flag, Info, Sparkles, X } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import { useCitation } from "../api/hooks";
import type { Author, CitationResult, Evidence, RecordT, Style, Suggestion, Verdict } from "../api/types";
import { settings } from "../lib/settings";
import { safeUrl } from "../lib/url";
import { FLAG_LABELS, SOURCE_NAMES, VERDICTS, VERDICT_ORDER, confidenceLabel } from "../lib/verdicts";
import { ClaimChecks } from "./ClaimChecks";
import { CopyButton, ErrorNote, Segmented, Spinner, VerdictBadge, cx } from "./ui";

const authors = (list: Author[] | undefined, truncated = false) =>
  list && list.length
    ? list.map((a) => (a.given ? `${a.given} ${a.family}` : a.family)).join(", ") + (truncated ? ", et al." : "")
    : null;

function EvidenceChip({ ev }: { ev: Evidence }) {
  const name = SOURCE_NAMES[ev.source] ?? ev.source;
  const url = safeUrl(ev.url);
  const content = (
    <>
      {name}
      {url && <ExternalLink className="size-3" />}
    </>
  );
  const cls =
    "inline-flex items-center gap-1 rounded-md bg-ink-100 px-1.5 py-0.5 text-[11px] font-medium text-ink-700 hover:bg-ink-200 dark:bg-ink-800 dark:text-ink-200 dark:hover:bg-ink-700";
  return url ? (
    <a href={url} target="_blank" rel="noopener noreferrer" className={cls} title={`${ev.operation}: ${ev.query}`}>
      {content}
    </a>
  ) : (
    <span className={cls}>{content}</span>
  );
}

type Row = { field: string; label: string; claimed: string | null; actual: string | null };

function comparisonRows(r: CitationResult): Row[] {
  const ref = r.reference;
  const rec: RecordT | undefined = r.best_match?.record;
  return [
    { field: "title", label: "Title", claimed: ref.title ?? null, actual: rec?.title ?? null },
    { field: "authors", label: "Authors", claimed: authors(ref.authors, ref.authors_truncated), actual: authors(rec?.authors) },
    { field: "year", label: "Year", claimed: ref.year?.toString() ?? null, actual: rec?.year?.toString() ?? null },
    { field: "venue", label: "Venue", claimed: ref.container_title ?? null, actual: rec?.container_title ?? null },
    { field: "volume", label: "Volume", claimed: ref.volume ?? null, actual: rec?.volume ?? null },
    { field: "pages", label: "Pages", claimed: ref.pages ?? null, actual: rec?.pages ?? null },
    { field: "doi", label: "DOI", claimed: ref.ids?.doi ?? null, actual: rec?.doi ?? null },
  ].filter((row) => row.claimed || row.actual);
}

function Comparison({ result }: { result: CitationResult }) {
  const flagged = new Set(
    (result.discrepancies ?? []).filter((d) => d.severity !== "info").map((d) => d.field),
  );
  const rows = comparisonRows(result);
  if (!result.best_match) return null;
  return (
    <section>
      <h3 className="label mb-2">As cited vs. found record</h3>
      <div className="overflow-hidden rounded-lg border border-ink-200 dark:border-ink-800">
        <table className="w-full table-fixed text-sm">
          <thead className="bg-ink-50 text-left text-xs text-ink-500 dark:bg-ink-800/50 dark:text-ink-400">
            <tr>
              <th className="w-20 px-3 py-2 font-medium">Field</th>
              <th className="px-3 py-2 font-medium">As cited</th>
              <th className="px-3 py-2 font-medium">Found ({SOURCE_NAMES[result.best_match.record.source] ?? result.best_match.record.source})</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-ink-100 dark:divide-ink-800">
            {rows.map((row) => {
              const bad = flagged.has(row.field);
              return (
                <tr key={row.field} className={cx(bad && "bg-amber-50/70 dark:bg-amber-950/30")}>
                  <td className="px-3 py-2 align-top text-xs font-medium text-ink-500">{row.label}</td>
                  <td className={cx("px-3 py-2 align-top break-words", bad && "text-amber-900 line-through decoration-amber-500/60 dark:text-amber-200")}>
                    {row.claimed ?? <span className="text-ink-400">—</span>}
                  </td>
                  <td className={cx("px-3 py-2 align-top break-words", bad && "font-medium")}>
                    {row.actual ?? <span className="text-ink-400">—</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function SuggestionBlock({ items, title }: { items: Suggestion[]; title: string }) {
  const [style, setStyle] = useState<Style>(settings.getStyle());
  if (!items.length) return null;
  return (
    <section>
      <div className="mb-2 flex items-center justify-between gap-2">
        <h3 className="label">{title}</h3>
        <Segmented<Style>
          ariaLabel="Citation style"
          value={style}
          onChange={setStyle}
          options={[
            { value: "apa", label: "APA" },
            { value: "ieee", label: "IEEE" },
            { value: "bibtex", label: "BibTeX" },
          ]}
        />
      </div>
      <ol className="space-y-2">
        {items.map((s, i) => {
          const text = s.formatted?.[style] ?? "";
          const link = s.record.doi ? `https://doi.org/${s.record.doi}` : safeUrl(s.record.url);
          return (
            <li key={i} className="rounded-lg border border-ink-200 p-3 dark:border-ink-800">
              <p className={cx("text-sm break-words", style === "bibtex" && "font-mono text-xs whitespace-pre-wrap")}>{text}</p>
              {s.relevance_note && (
                <p className="mt-1.5 flex gap-1.5 text-xs text-ink-600 dark:text-ink-400">
                  {s.method === "llm" ? <Sparkles className="mt-0.5 size-3 shrink-0" /> : <Info className="mt-0.5 size-3 shrink-0" />}
                  {s.relevance_note}
                </p>
              )}
              <div className="mt-2 flex items-center gap-1">
                <CopyButton text={text} />
                {link && (
                  <a className="btn-ghost px-2 py-1 text-xs" href={link} target="_blank" rel="noopener noreferrer">
                    <ExternalLink className="size-3.5" /> Open
                  </a>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function EvidenceTrail({ evidence }: { evidence: Evidence[] }) {
  const [open, setOpen] = useState(false);
  return (
    <section>
      <button type="button" className="label flex items-center gap-1" onClick={() => setOpen(!open)} aria-expanded={open}>
        <ChevronDown className={cx("size-3.5 transition", !open && "-rotate-90")} />
        Evidence trail ({evidence.length} lookups)
      </button>
      {open && (
        <ul className="mt-2 divide-y divide-ink-100 rounded-lg border border-ink-200 text-xs dark:divide-ink-800 dark:border-ink-800">
          {evidence.map((e) => (
            <li key={e.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2">
              <span className="font-mono text-ink-400">{e.id}</span>
              <span className="font-medium">{SOURCE_NAMES[e.source] ?? e.source}</span>
              <span className="text-ink-500">{e.operation}</span>
              <span
                className={cx(
                  "rounded px-1.5 py-0.5 font-medium",
                  e.status === "found" && "bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
                  e.status === "not_found" && "bg-ink-100 text-ink-600 dark:bg-ink-800 dark:text-ink-300",
                  !["found", "not_found"].includes(e.status) && "bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300",
                )}
              >
                {e.status.replace("_", " ")}
              </span>
              <span className="min-w-0 flex-1 truncate text-ink-500" title={e.query}>{e.query}</span>
              <span className="text-ink-400">{e.cached ? "cached" : `${e.latency_ms} ms`}</span>
              {safeUrl(e.url) && (
                <a href={safeUrl(e.url)} target="_blank" rel="noopener noreferrer" className="text-brand-600 dark:text-brand-500" aria-label="Open source">
                  <ExternalLink className="size-3.5" />
                </a>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function FeedbackForm({ checkId, result }: { checkId: string; result: CitationResult }) {
  const [verdict, setVerdict] = useState<Verdict | "">("");
  const [comment, setComment] = useState("");
  const send = useMutation({
    mutationFn: () => api.sendFeedback(checkId, result.index, verdict as Verdict, comment),
  });
  if (send.isSuccess) return <p className="text-sm text-emerald-700 dark:text-emerald-400">Thanks, your feedback helps improve the evaluation set.</p>;
  return (
    <details className="group text-sm">
      <summary className="label flex cursor-pointer list-none items-center gap-1">
        <Flag className="size-3.5" /> Is this verdict wrong?
      </summary>
      <div className="mt-2 space-y-2">
        <select className="input" value={verdict} onChange={(e) => setVerdict(e.target.value as Verdict)}>
          <option value="">The correct verdict is…</option>
          {VERDICT_ORDER.filter((v) => v !== result.verdict).map((v) => (
            <option key={v} value={v}>{VERDICTS[v].label}</option>
          ))}
        </select>
        <textarea className="input min-h-16" placeholder="Optional: what did we get wrong?" value={comment} onChange={(e) => setComment(e.target.value)} maxLength={2000} />
        <button type="button" className="btn-outline" disabled={!verdict || send.isPending} onClick={() => send.mutate()}>
          {send.isPending && <Spinner />} Send feedback
        </button>
        {send.error && <ErrorNote>{(send.error as Error).message}</ErrorNote>}
      </div>
    </details>
  );
}

export function CitationDrawer({ checkId, index, onClose }: { checkId: string; index: number | null; onClose: () => void }) {
  const { data: result, isLoading, error } = useCitation(checkId, index);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  if (index === null) return null;

  const evidence = new Map((result?.evidence ?? []).map((e) => [e.id, e]));
  const corrections = (result?.suggestions ?? []).filter((s) => s.kind === "correction");
  const alternatives = (result?.suggestions ?? []).filter((s) => s.kind === "alternative");

  return (
    <div className="fixed inset-0 z-40 flex justify-end" role="dialog" aria-modal="true" aria-label={`Citation ${index + 1}`}>
      <button type="button" className="absolute inset-0 bg-ink-950/40" onClick={onClose} aria-label="Close details" />
      <aside className="relative flex h-full w-full max-w-2xl flex-col overflow-hidden border-l border-ink-200 bg-white shadow-2xl dark:border-ink-800 dark:bg-ink-900">
        <header className="flex items-center gap-3 border-b border-ink-200 px-5 py-3 dark:border-ink-800">
          <span className="font-mono text-sm text-ink-400">#{index + 1}</span>
          {result && <VerdictBadge verdict={result.verdict} size="md" />}
          {result && (
            <span className="text-xs text-ink-500">
              {confidenceLabel(result.confidence)} confidence ({result.confidence.toFixed(2)})
            </span>
          )}
          <button type="button" className="btn-ghost ml-auto px-2" onClick={onClose} aria-label="Close">
            <X className="size-4" />
          </button>
        </header>
        <div className="flex-1 space-y-6 overflow-y-auto px-5 py-5">
          {isLoading && <Spinner />}
          {error && <ErrorNote>{(error as Error).message}</ErrorNote>}
          {result && (
            <>
              <blockquote className="border-l-2 border-ink-300 pl-3 font-serif text-[15px] italic text-ink-700 dark:border-ink-600 dark:text-ink-300">
                {result.reference.raw}
              </blockquote>

              {result.explanation && (
                <section className="space-y-3">
                  <div className="flex items-center justify-between gap-2">
                    <h3 className="label">Why this verdict</h3>
                    <span className="inline-flex items-center gap-1 text-[11px] text-ink-500">
                      {result.explanation.mode === "llm" ? (
                        <><Sparkles className="size-3" /> LLM-written, checked against evidence</>
                      ) : (
                        <>Rule-based explanation</>
                      )}
                    </span>
                  </div>
                  <p className="font-medium">{result.explanation.headline}</p>
                  <ol className="list-decimal space-y-2 pl-5 text-sm text-ink-700 marker:text-ink-400 dark:text-ink-300">
                    {(result.explanation.reasons ?? []).map((r, i) => (
                      <li key={i}>
                        {r.text}{" "}
                        <span className="inline-flex flex-wrap gap-1 align-middle">
                          {Array.from(new Map((r.evidence_ids ?? []).map((id) => [evidence.get(id)?.source ?? id, evidence.get(id)])).values())
                            .filter((e): e is Evidence => !!e)
                            .map((e) => <EvidenceChip key={e.id} ev={e} />)}
                        </span>
                      </li>
                    ))}
                  </ol>
                  <p className="rounded-lg bg-brand-500/8 px-3 py-2 text-sm text-brand-700 dark:bg-brand-500/15 dark:text-brand-500">
                    {result.explanation.recommendation}
                  </p>
                </section>
              )}

              {(result.flags ?? []).length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {(result.flags ?? []).map((f) => (
                    <span key={f} className={cx("rounded-md px-2 py-0.5 text-xs font-medium", f === "RETRACTED" ? "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200" : "bg-ink-100 text-ink-700 dark:bg-ink-800 dark:text-ink-300")}>
                      {FLAG_LABELS[f] ?? f}
                    </span>
                  ))}
                </div>
              )}

              <ClaimChecks checks={result.claim_checks ?? []} />
              <Comparison result={result} />
              <SuggestionBlock items={corrections} title="Corrected citation" />
              <SuggestionBlock
                items={alternatives}
                title={
                  result.verdict === "FABRICATED"
                    ? "Real alternatives: read before citing"
                    : "Papers that may support the claim: read before citing"
                }
              />

              {(result.risk_signals ?? []).length > 0 && (
                <section>
                  <h3 className="label mb-2">Offline warning signs</h3>
                  <ul className="list-disc space-y-1 pl-5 text-sm text-ink-700 dark:text-ink-300">
                    {(result.risk_signals ?? []).map((s) => <li key={s.code}>{s.message}</li>)}
                  </ul>
                </section>
              )}

              <EvidenceTrail evidence={result.evidence ?? []} />
              <FeedbackForm checkId={checkId} result={result} />
            </>
          )}
        </div>
      </aside>
    </div>
  );
}
