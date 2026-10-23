// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

type Deferred = { resolve: () => void; reject: (e: Error) => void };
const calls: { symbol: string; entry?: unknown; done: Deferred }[] = [];
const watched = new Set<string>();
const held = new Set<string>();

function deferredCall(symbol: string, entry?: unknown): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    calls.push({ symbol, entry, done: { resolve, reject } });
  });
}

vi.mock("../components/Watch", () => ({
  useWatchlist: () => ({
    add: (symbol: string) => deferredCall(symbol),
    isWatched: (symbol: string) => watched.has(symbol),
  }),
}));
vi.mock("../components/Positions", () => ({
  usePositions: () => ({
    open: (symbol: string, entry: unknown) => deferredCall(symbol, entry),
    isHeld: (symbol: string) => held.has(symbol),
  }),
}));

const { AddSymbol } = await import("./Watchlist");
const { AddPosition } = await import("./Positions");

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  calls.length = 0;
  watched.clear();
  held.clear();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

/** Type into a React-controlled input the way the browser does (native setter + input event). */
function type(input: HTMLInputElement, text: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
  act(() => {
    input.focus();
    setter.call(input, text);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

/** Enter in a field: the browser's implicit submission fires the form's submit event. */
function enter(input: HTMLInputElement) {
  act(() => {
    input.form!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
}

async function settle(i: number, fail?: string) {
  await act(async () => {
    if (fail) calls[i].done.reject(new Error(fail));
    else calls[i].done.resolve();
  });
}

describe("Watchlist add box keeps focus between tickers", () => {
  it("SPY ⏎ QQQ ⏎ while SPY is still in flight: focus stays, field clears, both are added in order", async () => {
    act(() => root.render(<MemoryRouter><AddSymbol /></MemoryRouter>));
    const input = host.querySelector<HTMLInputElement>("#add-symbol-input")!;

    type(input, "spy");
    enter(input);
    expect(document.activeElement).toBe(input);
    expect(input.value).toBe("");
    expect(input.disabled).toBe(false);
    expect(calls.map((c) => c.symbol)).toEqual(["SPY"]);

    type(input, "qqq");
    enter(input);
    expect(document.activeElement).toBe(input);
    expect(input.value).toBe("");
    // Queued, not dropped, and not sent until SPY's response is in (responses replace the whole list).
    expect(calls.map((c) => c.symbol)).toEqual(["SPY"]);
    expect(host.textContent).toContain("Adding SPY, QQQ…");

    await settle(0);
    expect(calls.map((c) => c.symbol)).toEqual(["SPY", "QQQ"]);
    await settle(1);
    expect(host.textContent).toContain("Added SPY, QQQ");
    expect(document.activeElement).toBe(input);
  });

  it("the + Add button also returns focus to the field, and failures are reported without losing the rest", async () => {
    act(() => root.render(<MemoryRouter><AddSymbol /></MemoryRouter>));
    const input = host.querySelector<HTMLInputElement>("#add-symbol-input")!;
    const button = host.querySelector<HTMLButtonElement>("button[type=submit]")!;

    type(input, "zzzz");
    act(() => button.focus());
    enter(input);
    expect(document.activeElement).toBe(input);
    type(input, "AMD");
    enter(input);
    await settle(0, "Unknown symbol");
    await settle(1);
    expect(host.textContent).toContain("Added AMD");
    expect(host.textContent).toContain("ZZZZ: Unknown symbol");
    expect(document.activeElement).toBe(input);
  });

  it("an already-watched or already-queued ticker is not sent twice", () => {
    watched.add("SPY");
    act(() => root.render(<MemoryRouter><AddSymbol /></MemoryRouter>));
    const input = host.querySelector<HTMLInputElement>("#add-symbol-input")!;
    type(input, "SPY");
    enter(input);
    type(input, "QQQ");
    enter(input);
    type(input, "QQQ");
    enter(input);
    expect(calls.map((c) => c.symbol)).toEqual(["QQQ"]);
    expect(host.textContent).toContain("QQQ is already being added");
    expect(document.activeElement).toBe(input);
  });
});

describe("Positions add box returns focus to the ticker field", () => {
  it("NVDA ⏎ (from the price field) AMD ⏎: focus goes back to the ticker, form clears, entries kept per ticker", async () => {
    act(() => root.render(<MemoryRouter><AddPosition /></MemoryRouter>));
    const ticker = host.querySelector<HTMLInputElement>("#add-position-input")!;
    const price = host.querySelector<HTMLInputElement>("input[aria-label='Entry price']")!;

    type(ticker, "nvda");
    type(price, "190.5");
    expect(document.activeElement).toBe(price);
    enter(price);
    expect(document.activeElement).toBe(ticker);
    expect(ticker.value).toBe("");
    expect(price.value).toBe("");
    expect(ticker.disabled || price.disabled).toBe(false);

    type(ticker, "amd");
    enter(ticker);
    expect(document.activeElement).toBe(ticker);
    expect(calls.map((c) => c.symbol)).toEqual(["NVDA"]);
    await settle(0);
    await settle(1);
    expect(calls.map((c) => c.symbol)).toEqual(["NVDA", "AMD"]);
    expect(calls[0].entry).toMatchObject({ entry_price: 190.5 });
    expect(calls[1].entry).toMatchObject({ entry_price: null });
    expect(host.textContent).toContain("Opened NVDA, AMD");
    expect(document.activeElement).toBe(ticker);
  });

  it("a bad price keeps the form and the focus where it is", () => {
    act(() => root.render(<MemoryRouter><AddPosition /></MemoryRouter>));
    const ticker = host.querySelector<HTMLInputElement>("#add-position-input")!;
    const price = host.querySelector<HTMLInputElement>("input[aria-label='Entry price']")!;
    type(ticker, "NVDA");
    type(price, "-3");
    enter(price);
    expect(calls).toHaveLength(0);
    expect(document.activeElement).toBe(price);
    expect(ticker.value).toBe("NVDA");
    expect(host.textContent).toContain("Entry price must be a positive number");
  });
});
