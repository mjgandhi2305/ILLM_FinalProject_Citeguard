import { ExternalLink, Quote } from "lucide-react";

import type { ClaimCheck, ClaimSupport } from "../api/types";
import { SOURCE_NAMES } from "../lib/verdicts";
import { safeUrl } from "../lib/url";
import { cx } from "./ui";

export const CLAIM_LABELS: Record<ClaimSupport, { label: string; cls: string }> = {
  SUPPORTS: {
    label: "Supported",
    cls: "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300",
  },
  PARTIAL: {
    label: "Partly supported",
    cls: "bg-amber-50 text-amber-800 dark:bg-amber-950/50 dark:text-amber-300",
  },
  NOT_SUPPORTED: {
    label: "Not supported",
    cls: "bg-red-50 text-red-700 dark:bg-red-950/60 dark:text-red-300",
  },
  CANNOT_DETERMINE: {
    label: "Can’t tell from the abstract",
    cls: "bg-ink-100 text-ink-700 dark:bg-ink-800 dark:text-ink-300",
  },
};

/** Claim-support hints: does the cited paper's abstract back the sentence citing it? */
export function ClaimChecks({ checks }: { checks: ClaimCheck[] }) {
  if (!checks.length) return null;
  return (
    <section className="space-y-3" aria-labelledby="claim-checks">
      <div className="flex items-center justify-between gap-2">
        <h3 id="claim-checks" className="label">Does the paper support the claim?</h3>
        <span className="text-[11px] text-ink-500">Abstract only: a hint, not a verdict</span>
      </div>
      <ul className="space-y-3">
        {checks.map((c, i) => {
          const meta = CLAIM_LABELS[c.label];
          const link = safeUrl(c.abstract_url);
          return (
            <li key={i} className="rounded-lg border border-ink-200 p-3 text-sm dark:border-ink-800">
              <span className={cx("rounded-md px-2 py-0.5 text-xs font-medium", meta.cls)}>{meta.label}</span>
              <p className="mt-2 text-ink-700 dark:text-ink-300">
                <span className="text-ink-500">Cited for: </span>“{c.claim}”
              </p>
              <p className="mt-1.5">{c.rationale}</p>
              {c.quote && (
                <blockquote className="mt-2 flex gap-2 rounded-md bg-ink-50 px-3 py-2 text-[13px] text-ink-700 dark:bg-ink-800/60 dark:text-ink-300">
                  <Quote className="mt-0.5 size-3.5 shrink-0 text-ink-400" />
                  <span>
                    {c.quote}
                    {link && (
                      <a href={link} target="_blank" rel="noopener noreferrer" className="ml-1.5 inline-flex items-center gap-0.5 text-xs text-brand-600 dark:text-brand-500">
                        {SOURCE_NAMES[c.abstract_source ?? ""] ?? "Source"} <ExternalLink className="size-3" />
                      </a>
                    )}
                  </span>
                </blockquote>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
