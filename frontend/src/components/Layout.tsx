import { KeyRound, Monitor, Moon, Sun } from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";

import { settings, type Theme } from "../lib/settings";
import { SettingsDialog } from "./SettingsDialog";
import { cx } from "./ui";

const THEMES: { value: Theme; icon: typeof Sun; label: string }[] = [
  { value: "light", icon: Sun, label: "Light" },
  { value: "dark", icon: Moon, label: "Dark" },
  { value: "system", icon: Monitor, label: "System" },
];

export function Layout() {
  const [theme, setTheme] = useState<Theme>(settings.getTheme());
  const [settingsOpen, setSettingsOpen] = useState(false);
  const next = THEMES[(THEMES.findIndex((t) => t.value === theme) + 1) % THEMES.length]!;
  const Current = THEMES.find((t) => t.value === theme)!.icon;

  const link = ({ isActive }: { isActive: boolean }) =>
    cx(
      "rounded-md px-2.5 py-1.5 text-sm font-medium whitespace-nowrap transition sm:px-3",
      isActive
        ? "bg-ink-100 text-ink-900 dark:bg-ink-800 dark:text-white"
        : "text-ink-600 hover:text-ink-900 dark:text-ink-300 dark:hover:text-white",
    );

  return (
    <div className="flex min-h-dvh flex-col">
      <header className="sticky top-0 z-30 border-b border-ink-200 bg-white/85 backdrop-blur dark:border-ink-800 dark:bg-ink-950/85">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-2 px-4 sm:gap-4">
          <NavLink to="/" className="flex items-center gap-2 font-semibold tracking-tight">
            <span className="grid size-7 place-items-center rounded-lg bg-brand-700 text-white">
              <svg viewBox="0 0 24 24" className="size-4" aria-hidden>
                <path d="M6 12.5l4 4 8-9" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </span>
            CiteGuard
          </NavLink>
          <nav className="flex items-center gap-1">
            <NavLink to="/" end className={link}>
              New check
            </NavLink>
            <NavLink to="/history" className={link}>
              History
            </NavLink>
          </nav>
          <div className="ml-auto flex items-center gap-1">
            <button
              type="button"
              className="btn-ghost px-2"
              onClick={() => {
                settings.setTheme(next.value);
                setTheme(next.value);
              }}
              aria-label={`Theme: ${theme}. Switch to ${next.label}`}
              title={`Theme: ${theme}`}
            >
              <Current className="size-4" />
            </button>
            <button
              type="button"
              className="btn-ghost px-2"
              onClick={() => setSettingsOpen(true)}
              aria-label="API key settings"
            >
              <KeyRound className="size-4" />
              <span className="hidden sm:inline">API key</span>
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8">
        <Outlet />
      </main>
      <footer className="border-t border-ink-200 py-6 text-center text-xs text-ink-500 dark:border-ink-800 dark:text-ink-400">
        Verdicts come from Crossref, OpenAlex, Semantic Scholar, arXiv, PubMed and doi.org. “Unverifiable” does not mean fake.
      </footer>
      <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}
