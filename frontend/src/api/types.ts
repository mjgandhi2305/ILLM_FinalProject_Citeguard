import type { components } from "./schema";

type S = components["schemas"];

export type Verdict = S["Verdict"];
export type CheckOptions = S["CheckOptions"];
export type CheckCreated = S["CheckCreated"];
export type CheckOut = S["CheckOut"];
export type CheckListItem = S["CheckListItem"];
export type CitationSummary = S["CitationSummary"];
export type CitationResult = S["CitationResult"];
export type Evidence = S["Evidence"];
export type Discrepancy = S["Discrepancy"];
export type Suggestion = S["Suggestion"];
export type RecordT = S["Record"];
export type Author = S["Author"];
export type ClaimCheck = S["ClaimCheck"];
export type ClaimSupport = S["ClaimSupport"];
export type SourceHealth = S["SourceHealth"];

export type Style = "apa" | "ieee" | "bibtex";
export type ExportFormat = "html" | "bib" | "csv" | "json" | "md";
