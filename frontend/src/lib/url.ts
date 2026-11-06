/** Links come from third-party records: only http(s) URLs are rendered as links. */
export function safeUrl(url: string | null | undefined): string | undefined {
  return url && /^https?:\/\//i.test(url) ? url : undefined;
}
