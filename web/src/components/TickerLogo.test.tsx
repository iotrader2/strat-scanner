import type { ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { TickerLogo, TickerLogoView, logoLetter, logoUrl } from "./TickerLogo";

type Props = { children?: unknown; onError?: () => void; src?: string };

function findImg(node: unknown): ReactElement<Props> | undefined {
  if (!node || typeof node !== "object") return undefined;
  if (Array.isArray(node)) return node.map(findImg).find(Boolean);
  const el = node as ReactElement<Props>;
  if (el.type === "img") return el;
  return findImg(el.props?.children);
}

describe("TickerLogo", () => {
  it("lazy-loads the same-origin logo at a fixed size over a letter avatar", () => {
    const html = renderToStaticMarkup(<TickerLogo symbol="aapl" size={20} />);
    expect(html).toContain('style="width:20px;height:20px;font-size:10px"');
    expect(html).toContain('<span class="ticker-logo-letter">A</span>');
    expect(html).toContain('src="/api/logo/AAPL"');
    expect(html).toContain('loading="lazy"');
    expect(html).toContain('decoding="async"');
    expect(html).toContain('width="20" height="20"');
    expect(html).toContain('alt=""');
    expect(html).toContain('aria-hidden="true"');
  });

  it("reports a broken image so the parent swaps to the letter", () => {
    const onFail = vi.fn();
    const img = findImg(TickerLogoView({ symbol: "SKYD", size: 14, failed: false, onFail }));
    expect(img?.props.src).toBe("/api/logo/SKYD");
    img?.props.onError?.();
    expect(onFail).toHaveBeenCalledOnce();
  });

  it("shows only the same-size letter avatar once failed", () => {
    const html = renderToStaticMarkup(<TickerLogoView symbol="SKYD" size={14} failed onFail={() => {}} />);
    expect(html).not.toContain("<img");
    expect(html).toContain("no-logo");
    expect(html).toContain('style="width:14px;height:14px;font-size:7px"');
    expect(html).toContain(">S</span>");
  });

  it("encodes class shares and picks a safe letter", () => {
    expect(logoUrl("BRK-B")).toBe("/api/logo/BRK-B");
    expect(logoUrl("a/b")).toBe("/api/logo/A%2FB");
    expect(logoLetter("3M")).toBe("3");
    expect(logoLetter("$X")).toBe("?");
  });
});
