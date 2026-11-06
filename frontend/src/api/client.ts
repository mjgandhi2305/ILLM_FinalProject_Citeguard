import { settings } from "../lib/settings";
import type {
  CheckCreated,
  CheckListItem,
  CheckOptions,
  CheckOut,
  CitationResult,
  ExportFormat,
  SourceHealth,
  Style,
  Verdict,
} from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public retryAfter?: number,
  ) {
    super(message);
  }
}

export function authHeaders(): Record<string, string> {
  const key = settings.getApiKey();
  return key ? { "X-API-Key": key } : {};
}

async function errorFrom(res: Response): Promise<ApiError> {
  let message = res.statusText || `HTTP ${res.status}`;
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") message = body.detail;
    else if (Array.isArray(body?.detail)) message = body.detail.map((d: { msg: string }) => d.msg).join("; ");
  } catch {
    /* non-JSON error body */
  }
  if (res.status === 401) message = "Missing or invalid API key — add one in Settings.";
  const retry = Number(res.headers.get("retry-after")) || undefined;
  return new ApiError(res.status, message, retry);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { ...authHeaders(), ...(init.headers ?? {}) },
  });
  if (!res.ok) throw await errorFrom(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export type NewCheck =
  | { kind: "text"; text: string }
  | { kind: "bibtex"; bibtex: string }
  | { kind: "citation"; citation: string };

export const api = {
  createCheck(input: NewCheck, options: CheckOptions): Promise<CheckCreated> {
    const { kind, ...content } = input;
    void kind;
    return request("/api/v1/checks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...content, options }),
    });
  },
  uploadCheck(file: File, options: CheckOptions): Promise<CheckCreated> {
    const form = new FormData();
    form.append("file", file);
    form.append("options", JSON.stringify(options));
    return request("/api/v1/checks/upload", { method: "POST", body: form });
  },
  getCheck: (id: string) => request<CheckOut>(`/api/v1/checks/${id}`),
  listChecks: () => request<CheckListItem[]>("/api/v1/checks"),
  getCitation: (id: string, index: number) =>
    request<CitationResult>(`/api/v1/checks/${id}/citations/${index}`),
  deleteCheck: (id: string) => request<void>(`/api/v1/checks/${id}`, { method: "DELETE" }),
  sendFeedback: (id: string, index: number, user_verdict: Verdict, comment?: string) =>
    request(`/api/v1/checks/${id}/citations/${index}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_verdict, comment: comment || null }),
    }),
  sourcesHealth: () => request<SourceHealth>("/api/v1/sources/health"),

  /** Downloads go through fetch so the API key header is sent. */
  async download(id: string, format: ExportFormat, style: Style): Promise<void> {
    const res = await fetch(`/api/v1/checks/${id}/export?format=${format}&style=${style}`, {
      headers: authHeaders(),
    });
    if (!res.ok) throw await errorFrom(res);
    const blob = await res.blob();
    const disposition = res.headers.get("content-disposition") ?? "";
    const name = /filename="([^"]+)"/.exec(disposition)?.[1] ?? `citeguard.${format}`;
    const url = URL.createObjectURL(blob);
    if (format === "html") {
      window.open(url, "_blank", "noopener");
    } else {
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      a.click();
    }
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  },
};
