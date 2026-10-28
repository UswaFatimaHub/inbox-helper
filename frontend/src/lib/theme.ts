import { useEffect, useState } from "react";

export type Theme = "light" | "dark";
const KEY = "inbox-theme"; // also read by the script in index.html, which sets the class before first paint

/** Light or dark, remembered per browser. Without a saved choice it follows the system setting. */
export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() => (document.documentElement.classList.contains("dark") ? "dark" : "light"));
  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);
  const toggle = () =>
    setTheme((t) => {
      const next = t === "dark" ? "light" : "dark";
      try {
        localStorage.setItem(KEY, next);
      } catch {
        /* storage blocked: the choice lasts until reload */
      }
      return next;
    });
  return [theme, toggle];
}
