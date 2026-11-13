import { describe, expect, it } from "vitest";
import { DEFAULT_PAGE_SIZE, normalizePageSize, paginate } from "./pagination";

const nums = (n: number) => Array.from({ length: n }, (_, i) => i + 1);

describe("paginate", () => {
  it("slices pages and reports the visible range", () => {
    const s = paginate(nums(60), 1, 25);
    expect(s.rows).toEqual(nums(50).slice(25));
    expect(s).toMatchObject({ page: 1, pages: 3, from: 26, to: 50, total: 60 });
    expect(paginate(nums(60), 2, 25)).toMatchObject({ from: 51, to: 60 });
  });

  it("clamps a page past the end (rows were filtered away) and below zero", () => {
    expect(paginate(nums(30), 5, 25)).toMatchObject({ page: 1, from: 26, to: 30 });
    expect(paginate(nums(30), -1, 25)).toMatchObject({ page: 0, from: 1 });
  });

  it("shows everything for size 0 or when it fits, and handles no rows", () => {
    expect(paginate(nums(300), 3, 0)).toMatchObject({ pages: 1, from: 1, to: 300 });
    expect(paginate(nums(10), 2, 25)).toMatchObject({ page: 0, pages: 1, to: 10 });
    expect(paginate([], 0, 25)).toMatchObject({ rows: [], from: 0, to: 0, total: 0, pages: 1 });
  });

  it("only keeps known page sizes", () => {
    expect(normalizePageSize(100)).toBe(100);
    expect(normalizePageSize(0)).toBe(0);
    expect(normalizePageSize(37)).toBe(DEFAULT_PAGE_SIZE);
    expect(normalizePageSize("50")).toBe(DEFAULT_PAGE_SIZE);
  });
});
