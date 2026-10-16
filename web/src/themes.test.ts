import { describe, expect, it } from "vitest";
import { matchesTheme, NO_THEME, scanThemeHref, themeName, themeOptions } from "./themes";

const THEMES = [
  { id: "memory", name: "Memory & storage", count: 4 },
  { id: "cyber", name: "Cybersecurity", count: 8 },
];

describe("theme filter", () => {
  const mu = { theme: "memory", secondary_themes: [] as string[] };
  const net = { theme: "cloud", secondary_themes: ["cyber"] };
  const etf = { theme: null, secondary_themes: [] as string[] };

  it("passes everything when no theme is chosen", () => {
    for (const r of [mu, net, etf]) expect(matchesTheme(r, "")).toBe(true);
  });

  it("matches the primary theme", () => {
    expect(matchesTheme(mu, "memory")).toBe(true);
    expect(matchesTheme(mu, "cyber")).toBe(false);
  });

  it("also matches secondary themes", () => {
    expect(matchesTheme(net, "cyber")).toBe(true);
    expect(matchesTheme(net, "cloud")).toBe(true);
    expect(matchesTheme(net, "memory")).toBe(false);
  });

  it("selects rows outside every theme", () => {
    expect(matchesTheme(etf, NO_THEME)).toBe(true);
    expect(matchesTheme(mu, NO_THEME)).toBe(false);
    expect(matchesTheme(net, NO_THEME)).toBe(false);
    expect(matchesTheme({ theme: undefined }, NO_THEME)).toBe(true);
  });
});

describe("theme options", () => {
  it("lists all themes, themes by name, then the no-theme option", () => {
    expect(themeOptions(THEMES)).toEqual([
      { value: "", label: "All themes" },
      { value: "cyber", label: "Cybersecurity" },
      { value: "memory", label: "Memory & storage" },
      { value: NO_THEME, label: "No theme (ETFs, others)" },
    ]);
  });

  it("names a theme id, falling back to the id", () => {
    expect(themeName(THEMES, "memory")).toBe("Memory & storage");
    expect(themeName(THEMES, "unknown")).toBe("unknown");
    expect(themeName(THEMES, NO_THEME)).toBe("No theme");
  });

  it("links to the scanner with the theme filter", () => {
    expect(scanThemeHref("ai-hardware")).toBe("/?theme=ai-hardware");
  });
});
