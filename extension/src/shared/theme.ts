import type { ResolvedTheme, ThemePreference } from "./types";

const THEME_PREFERENCE_CACHE_KEY = "summarix_theme_preference";

function canUseChromeStorage(): boolean {
  return typeof chrome !== "undefined" && Boolean(chrome.storage?.local);
}

export function normalizeThemePreference(value: unknown): ThemePreference {
  if (value === "light" || value === "dark") return value;
  return "default";
}

export function getSystemTheme(): ResolvedTheme {
  if (typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches) {
    return "dark";
  }
  return "light";
}

export function resolveThemePreference(preference: ThemePreference, systemTheme: ResolvedTheme): ResolvedTheme {
  return preference === "default" ? systemTheme : preference;
}

export function applyThemePreference(preference: ThemePreference, systemTheme = getSystemTheme()): ResolvedTheme {
  const resolvedTheme = resolveThemePreference(preference, systemTheme);
  if (typeof document !== "undefined") {
    document.documentElement.dataset.theme = resolvedTheme;
    document.documentElement.style.colorScheme = resolvedTheme;
  }
  return resolvedTheme;
}

export async function readCachedThemePreference(): Promise<ThemePreference> {
  try {
    if (canUseChromeStorage()) {
      const stored = await chrome.storage.local.get(THEME_PREFERENCE_CACHE_KEY);
      return normalizeThemePreference(stored[THEME_PREFERENCE_CACHE_KEY]);
    }
    return normalizeThemePreference(window.localStorage.getItem(THEME_PREFERENCE_CACHE_KEY));
  } catch {
    return "default";
  }
}

export async function cacheThemePreference(preference: ThemePreference): Promise<void> {
  const normalizedPreference = normalizeThemePreference(preference);
  try {
    if (canUseChromeStorage()) {
      await chrome.storage.local.set({ [THEME_PREFERENCE_CACHE_KEY]: normalizedPreference });
      return;
    }
    window.localStorage.setItem(THEME_PREFERENCE_CACHE_KEY, normalizedPreference);
  } catch {
    // 本地镜像只影响启动首帧，失败时以后端设置为准。
  }
}