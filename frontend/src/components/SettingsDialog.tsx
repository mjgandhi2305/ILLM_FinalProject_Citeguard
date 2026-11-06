import { useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import { settings } from "../lib/settings";

export function SettingsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const qc = useQueryClient();
  const [key, setKey] = useState(settings.getApiKey() ?? "");
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      setKey(settings.getApiKey() ?? "");
      setStatus(null);
      dialog.showModal();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  async function save() {
    settings.setApiKey(key);
    setStatus("Checking…");
    try {
      const health = await api.sourcesHealth();
      setStatus(`Connected. LLM explanations ${health.llm.enabled ? "on" : "off"}.`);
      qc.invalidateQueries();
    } catch (e) {
      setStatus((e as Error).message);
    }
  }

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      className="m-auto w-[min(92vw,28rem)] rounded-xl border border-ink-200 bg-white p-0 text-ink-900 shadow-xl backdrop:bg-ink-950/40 dark:border-ink-800 dark:bg-ink-900 dark:text-ink-100"
    >
      <div className="flex items-center justify-between border-b border-ink-200 px-5 py-3 dark:border-ink-800">
        <h2 className="font-semibold">API key</h2>
        <button type="button" className="btn-ghost px-2" onClick={onClose} aria-label="Close">
          <X className="size-4" />
        </button>
      </div>
      <div className="space-y-3 px-5 py-4">
        <p className="text-sm text-ink-600 dark:text-ink-300">
          Create a key with <code className="rounded bg-ink-100 px-1 dark:bg-ink-800">citeguard create-key --name you</code>.
          It is stored only in this browser. Leave empty if the server runs with authentication off.
        </p>
        <input
          className="input font-mono"
          type="password"
          autoComplete="off"
          placeholder="cg_…"
          value={key}
          onChange={(e) => setKey(e.target.value)}
        />
        {status && <p className="text-sm text-ink-600 dark:text-ink-300">{status}</p>}
      </div>
      <div className="flex justify-end gap-2 border-t border-ink-200 px-5 py-3 dark:border-ink-800">
        <button type="button" className="btn-outline" onClick={onClose}>
          Close
        </button>
        <button type="button" className="btn-primary" onClick={save}>
          Save &amp; test
        </button>
      </div>
    </dialog>
  );
}
