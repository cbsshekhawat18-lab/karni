/**
 * Light, dark or the system's choice, for the whole app.
 *
 *   <ThemeProvider>           // follows the system until the user picks
 *     <App />                 // <ThemeToggle /> anywhere lets them pick
 *   </ThemeProvider>
 *
 * The choice is kept per browser (localStorage) and applied as the `dark`
 * class on <html>, which is what @karni/ui's tokens switch on. Put
 * KARNI_THEME_SCRIPT in index.html's <head> (in a Vite app, `karniTheme()`
 * from `@karni/ui/vite` does) so the first paint already has the right
 * theme (no light flash before React starts).
 */
import * as React from "react";
import { registerComponentRole } from "../lib/roles";
import { Button } from "../components/primitives/button";
import { MonitorIcon, MoonIcon, SunIcon } from "../components/primitives/icons";
import { THEME_STORAGE_KEY } from "./script";

registerComponentRole("theme-toggle", "ThemeToggle");

export type ThemePreference = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

export { KARNI_THEME_SCRIPT, THEME_STORAGE_KEY } from "./script";

interface ThemeContextValue {
  /** What the user chose ("system" follows the operating system). */
  theme: ThemePreference;
  /** What is applied right now. */
  resolvedTheme: ResolvedTheme;
  setTheme: (theme: ThemePreference) => void;
}

const ThemeContext = React.createContext<ThemeContextValue | null>(null);

const DARK_QUERY = "(prefers-color-scheme: dark)";

function readStored(key: string): ThemePreference | null {
  try {
    const value = localStorage.getItem(key);
    return value === "light" || value === "dark" || value === "system" ? value : null;
  } catch {
    return null;
  }
}

function systemTheme(): ResolvedTheme {
  return typeof matchMedia === "function" && matchMedia(DARK_QUERY).matches ? "dark" : "light";
}

export interface ThemeProviderProps {
  /** Used until the user chooses; "system" by default. */
  defaultTheme?: ThemePreference;
  /** localStorage key for the user's choice; change it to keep apps on one origin apart. */
  storageKey?: string;
  /** The element that gets the `dark` class; <html> by default. */
  target?: () => HTMLElement;
  children?: React.ReactNode;
}

/** Applies the user's theme choice and keeps it; render it once around the app. */
export function ThemeProvider({
  defaultTheme = "system",
  storageKey = THEME_STORAGE_KEY,
  target,
  children,
}: ThemeProviderProps): React.ReactElement {
  const [theme, setThemeState] = React.useState<ThemePreference>(
    () => readStored(storageKey) ?? defaultTheme,
  );
  const [system, setSystem] = React.useState<ResolvedTheme>(systemTheme);

  React.useEffect(() => {
    if (typeof matchMedia !== "function") return undefined;
    const query = matchMedia(DARK_QUERY);
    const onChange = (): void => setSystem(query.matches ? "dark" : "light");
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  const resolvedTheme: ResolvedTheme = theme === "system" ? system : theme;

  React.useEffect(() => {
    const element = target ? target() : document.documentElement;
    element.classList.toggle("dark", resolvedTheme === "dark");
    element.style.colorScheme = resolvedTheme;
  }, [resolvedTheme, target]);

  const setTheme = React.useCallback(
    (next: ThemePreference) => {
      setThemeState(next);
      try {
        localStorage.setItem(storageKey, next);
      } catch {
        // Private windows and blocked storage: the choice lasts for this page.
      }
    },
    [storageKey],
  );

  const value = React.useMemo(
    () => ({ theme, resolvedTheme, setTheme }),
    [theme, resolvedTheme, setTheme],
  );
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

/** The theme choice and a setter; throws a descriptive error outside ThemeProvider. */
export function useTheme(): ThemeContextValue {
  const value = React.useContext(ThemeContext);
  if (value === null) {
    throw new Error(
      "useTheme must be used within <ThemeProvider>. Wrap your app in <ThemeProvider> (from @karni/ui).",
    );
  }
  return value;
}

const NEXT: Record<ThemePreference, ThemePreference> = {
  light: "dark",
  dark: "system",
  system: "light",
};
const LABEL: Record<ThemePreference, string> = {
  light: "Light",
  dark: "Dark",
  system: "System",
};

export interface ThemeToggleProps {
  className?: string;
}

/**
 * One button that cycles Light → Dark → System. Its accessible name says the
 * current choice and the next one ("Theme: Dark. Switch to System").
 */
export function ThemeToggle({ className }: ThemeToggleProps): React.ReactElement {
  const { theme, setTheme } = useTheme();
  const Icon = theme === "light" ? SunIcon : theme === "dark" ? MoonIcon : MonitorIcon;
  const label = `Theme: ${LABEL[theme]}. Switch to ${LABEL[NEXT[theme]]}`;
  return (
    <Button
      variant="ghost"
      size="icon"
      className={className}
      aria-label={label}
      title={label}
      onClick={() => setTheme(NEXT[theme])}
    >
      <Icon className="h-4 w-4" />
    </Button>
  );
}
