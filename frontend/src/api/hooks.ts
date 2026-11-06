import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api, authHeaders } from "./client";
import { streamEvents } from "./sse";
import type { CheckOut, CitationSummary } from "./types";

export const keys = {
  check: (id: string) => ["check", id] as const,
  citation: (id: string, index: number) => ["citation", id, index] as const,
  checks: ["checks"] as const,
  health: ["health"] as const,
};

function upsertCitation(check: CheckOut, c: CitationSummary, done?: number): CheckOut {
  const citations = [...check.citations.filter((x) => x.index !== c.index), c].sort(
    (a, b) => a.index - b.index,
  );
  return {
    ...check,
    status: check.status === "queued" ? "running" : check.status,
    citations,
    progress_done: done ?? Math.max(check.progress_done, citations.length),
  };
}

/**
 * Loads a check and keeps it live: SSE when possible, polling as a fallback.
 * Returns `live` = true while the event stream is connected.
 */
export function useLiveCheck(id: string) {
  const qc = useQueryClient();
  const [live, setLive] = useState(false);
  const [streamFailed, setStreamFailed] = useState(false);

  const query = useQuery({
    queryKey: keys.check(id),
    queryFn: () => api.getCheck(id),
    refetchInterval: (q) => {
      const status = q.state.data?.status;
      const running = status === "queued" || status === "running";
      return running && (streamFailed || !live) ? 2500 : false;
    },
  });

  const status = query.data?.status;
  const finished = status === "completed" || status === "failed";

  useEffect(() => {
    if (finished || streamFailed) return;
    const controller = new AbortController();
    setLive(true);
    streamEvents(
      `/api/v1/checks/${id}/events`,
      authHeaders(),
      ({ event, data }) => {
        const payload = JSON.parse(data);
        if (event === "snapshot") {
          qc.setQueryData(keys.check(id), payload as CheckOut);
        } else if (event === "check.parsed") {
          qc.setQueryData<CheckOut>(keys.check(id), (old) =>
            old ? { ...old, status: "running", progress_total: payload.total } : old,
          );
        } else if (event === "citation.verified" || event === "citation.enriched") {
          qc.setQueryData<CheckOut>(keys.check(id), (old) =>
            old ? upsertCitation(old, payload.citation, payload.progress_done) : old,
          );
          qc.invalidateQueries({ queryKey: keys.citation(id, payload.citation.index) });
        } else if (event === "check.completed" || event === "check.failed") {
          qc.invalidateQueries({ queryKey: keys.check(id) });
          qc.invalidateQueries({ queryKey: keys.checks });
        }
      },
      controller.signal,
    )
      .catch((err: unknown) => {
        if ((err as Error).name !== "AbortError") setStreamFailed(true);
      })
      .finally(() => setLive(false));
    return () => controller.abort();
  }, [id, finished, streamFailed, qc]);

  return { ...query, live };
}

export function useCitation(id: string, index: number | null) {
  return useQuery({
    queryKey: keys.citation(id, index ?? -1),
    queryFn: () => api.getCitation(id, index as number),
    enabled: index !== null,
  });
}
