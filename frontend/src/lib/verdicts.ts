import type { Verdict } from "../api/types";

export interface VerdictMeta {
  label: string;
  description: string;
  badge: string; // Tailwind classes for the pill
  dot: string; // Tailwind bg class for dots / bars
  severity: number; // lower = worse
}

export const VERDICTS: Record<Verdict, VerdictMeta> = {
  FABRICATED: {
    label: "Likely fabricated",
    description: "No such publication exists in any database we searched.",
    badge:
      "bg-red-50 text-red-700 ring-red-600/20 dark:bg-red-950/60 dark:text-red-300 dark:ring-red-400/30",
    dot: "bg-red-500",
    severity: 0,
  },
  MISATTRIBUTED: {
    label: "Misattributed",
    description: "The work exists, but authors or identifiers point elsewhere.",
    badge:
      "bg-orange-50 text-orange-700 ring-orange-600/20 dark:bg-orange-950/60 dark:text-orange-300 dark:ring-orange-400/30",
    dot: "bg-orange-500",
    severity: 1,
  },
  VERIFIED_WITH_ERRORS: {
    label: "Real, with errors",
    description: "A real paper, cited with wrong details (year, venue, pages…).",
    badge:
      "bg-amber-50 text-amber-800 ring-amber-600/25 dark:bg-amber-950/50 dark:text-amber-300 dark:ring-amber-400/30",
    dot: "bg-amber-400",
    severity: 2,
  },
  UNVERIFIABLE: {
    label: "Unverifiable",
    description: "Not enough evidence either way; check it manually.",
    badge:
      "bg-ink-100 text-ink-700 ring-ink-500/20 dark:bg-ink-800 dark:text-ink-300 dark:ring-ink-400/30",
    dot: "bg-ink-400",
    severity: 3,
  },
  VERIFIED: {
    label: "Verified",
    description: "Matches a real publication record.",
    badge:
      "bg-emerald-50 text-emerald-700 ring-emerald-600/20 dark:bg-emerald-950/60 dark:text-emerald-300 dark:ring-emerald-400/30",
    dot: "bg-emerald-500",
    severity: 4,
  },
};

export const VERDICT_ORDER = (Object.keys(VERDICTS) as Verdict[]).sort(
  (a, b) => VERDICTS[a].severity - VERDICTS[b].severity,
);

export const SOURCE_NAMES: Record<string, string> = {
  doi: "doi.org",
  crossref: "Crossref",
  openalex: "OpenAlex",
  semantic_scholar: "Semantic Scholar",
  arxiv: "arXiv",
  dblp: "DBLP",
  pubmed: "PubMed",
};

export const FLAG_LABELS: Record<string, string> = {
  RETRACTED: "Retracted",
  PREPRINT_HAS_PUBLISHED_VERSION: "Published version exists",
  CLAIM_NOT_SUPPORTED: "Claim not supported",
  LOW_PARSE_CONFIDENCE: "Parsed with low confidence",
  LLM_ADJUDICATED: "Match chosen by LLM",
  SOURCES_DEGRADED: "Some databases unavailable",
};

export function confidenceLabel(c: number): string {
  if (c >= 0.9) return "High";
  if (c >= 0.7) return "Medium";
  return "Low";
}
