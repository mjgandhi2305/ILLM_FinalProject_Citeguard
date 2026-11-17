/**
 * PDF text extractors mark a line-end hyphenation point with U+FFFE (sometimes a soft hyphen,
 * U+00AD), often followed by the line break: "learn￾ing" is the word "learning". Browsers draw
 * U+FFFE as a box. The backend now strips these on input; this also cleans results stored before
 * that fix, so they read correctly without re-running the check.
 */
const PDF_HYPHENATION = /[­￾]\r?\n?/g;

export function stripPdfArtifacts(text: string): string {
  return text.replace(PDF_HYPHENATION, "");
}

/** A `JSON.parse` reviver that cleans every string in an API response. */
export function cleanJson(_key: string, value: unknown): unknown {
  return typeof value === "string" ? stripPdfArtifacts(value) : value;
}
