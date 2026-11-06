import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { keys } from "../api/hooks";
import type { Verdict } from "../api/types";
import { ErrorNote, Spinner, cx } from "../components/ui";
import { VERDICTS, VERDICT_ORDER } from "../lib/verdicts";

const STATUS_STYLE: Record<string, string> = {
  completed: "text-emerald-700 dark:text-emerald-400",
  failed: "text-red-700 dark:text-red-400",
  running: "text-brand-600 dark:text-brand-500",
  queued: "text-ink-500",
};

export function HistoryPage() {
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({ queryKey: keys.checks, queryFn: api.listChecks });
  const remove = useMutation({
    mutationFn: api.deleteCheck,
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.checks }),
  });

  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">History</h1>
          <p className="text-sm text-ink-500">Checks and their results are deleted automatically after the retention period.</p>
        </div>
        <Link to="/" className="btn-primary">New check</Link>
      </div>
      {isLoading && <Spinner />}
      {error && <ErrorNote>{(error as Error).message}</ErrorNote>}
      {data && data.length === 0 && <p className="py-16 text-center text-ink-500">No checks yet.</p>}
      {data && data.length > 0 && (
        <ul className="card divide-y divide-ink-100 dark:divide-ink-800">
          {data.map((c) => {
            const counts = (c.summary?.by_verdict ?? {}) as Record<string, number>;
            const total = Object.values(counts).reduce((a, b) => a + b, 0);
            return (
              <li key={c.id} className="flex items-center gap-4 px-4 py-3">
                <Link to={`/checks/${c.id}`} className="min-w-0 flex-1">
                  <span className="block truncate font-medium hover:underline">{c.filename ?? c.input_kind}</span>
                  <span className="text-xs text-ink-500">
                    {new Date(c.created_at).toLocaleString()} ·{" "}
                    <span className={cx("font-medium", STATUS_STYLE[c.status])}>{c.status}</span>
                    {total > 0 && ` · ${total} citations`}
                  </span>
                </Link>
                <div className="hidden h-2 w-40 overflow-hidden rounded-full bg-ink-100 sm:flex dark:bg-ink-800" aria-hidden>
                  {VERDICT_ORDER.map((v: Verdict) =>
                    counts[v] ? <div key={v} className={VERDICTS[v].dot} style={{ width: `${(100 * counts[v]) / total}%` }} /> : null,
                  )}
                </div>
                <button
                  type="button"
                  className="btn-ghost px-2 text-ink-500 hover:text-red-600"
                  onClick={() => confirm("Delete this check and its results?") && remove.mutate(c.id)}
                  aria-label="Delete check"
                >
                  <Trash2 className="size-4" />
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
