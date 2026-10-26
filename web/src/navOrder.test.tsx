// @vitest-environment jsdom
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import App from "./App";

describe("top nav", () => {
  it("places Positions to the right of Alerts", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    );
    const nav = html.slice(html.indexOf("<nav>"), html.indexOf("</nav>"));
    const hrefs = [...nav.matchAll(/href="([^"]+)"/g)].map((m) => m[1]);
    expect(hrefs).toEqual(["/market", "/themes", "/", "/watchlist", "/alerts", "/positions"]);
  });
});
