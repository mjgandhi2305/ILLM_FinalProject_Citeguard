/** Per-browser preferences. Storage can be unavailable (private mode), so every access is guarded. */

const KEY = "cg.apiKey";
const THEME = "cg.theme";
const STYLE = "cg.style";

export type Theme = "system" | "light" | "dark";

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    /* storage unavailable: keep the in-memory value only */
  }
}

let memoryKey: string | null = read(KEY);

export const settings = {
  getApiKey: (): string | null => memoryKey,
  setApiKey(value: string | null) {
    memoryKey = value?.trim() || null;
    write(KEY, memoryKey);
  },
  getTheme: (): Theme => (read(THEME) as Theme | null) ?? "system",
  setTheme(theme: Theme) {
    write(THEME, theme);
    applyTheme(theme);
  },
  getStyle: (): "apa" | "ieee" | "bibtex" =>
    (read(STYLE) as "apa" | "ieee" | "bibtex" | null) ?? "apa",
  setStyle: (style: "apa" | "ieee" | "bibtex") => write(STYLE, style),
};

export function applyTheme(theme: Theme): void {
  const dark =
    theme === "dark" ||
    (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
}
