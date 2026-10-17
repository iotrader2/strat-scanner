import { describe, expect, it } from "vitest";
import { listKeyAction, opensList } from "./dropdownKeys";

const labels = ["All themes", "Cybersecurity", "Memory & storage", "Regional banks", "No theme (ETFs, others)"];

describe("dropdown keyboard navigation", () => {
  it("moves with the arrow keys and stops at the ends", () => {
    expect(listKeyAction("ArrowDown", 0, labels)).toEqual({ type: "move", index: 1 });
    expect(listKeyAction("ArrowDown", 4, labels)).toEqual({ type: "move", index: 4 });
    expect(listKeyAction("ArrowUp", 2, labels)).toEqual({ type: "move", index: 1 });
    expect(listKeyAction("ArrowUp", 0, labels)).toEqual({ type: "move", index: 0 });
  });

  it("jumps to the first and last option", () => {
    expect(listKeyAction("Home", 3, labels)).toEqual({ type: "move", index: 0 });
    expect(listKeyAction("End", 1, labels)).toEqual({ type: "move", index: 4 });
  });

  it("selects with Enter or Space and closes with Escape or Tab", () => {
    expect(listKeyAction("Enter", 2, labels)).toEqual({ type: "select", index: 2 });
    expect(listKeyAction(" ", 3, labels)).toEqual({ type: "select", index: 3 });
    expect(listKeyAction("Escape", 3, labels)).toEqual({ type: "close" });
    expect(listKeyAction("Tab", 3, labels)).toEqual({ type: "close" });
  });

  it("jumps to the next option starting with a typed letter, wrapping around", () => {
    expect(listKeyAction("m", 0, labels)).toEqual({ type: "move", index: 2 });
    expect(listKeyAction("N", 0, labels)).toEqual({ type: "move", index: 4 });
    expect(listKeyAction("a", 3, labels)).toEqual({ type: "move", index: 0 });
    expect(listKeyAction("c", 1, labels)).toEqual({ type: "move", index: 1 });
    expect(listKeyAction("z", 1, labels)).toEqual({ type: "none" });
  });

  it("ignores unrelated keys and handles an empty list", () => {
    expect(listKeyAction("Shift", 1, labels)).toEqual({ type: "none" });
    expect(listKeyAction("ArrowDown", 0, [])).toEqual({ type: "none" });
    expect(listKeyAction("Escape", 0, [])).toEqual({ type: "close" });
  });

  it("opens from the trigger with arrows, Enter or Space", () => {
    for (const k of ["ArrowDown", "ArrowUp", "Enter", " "]) expect(opensList(k)).toBe(true);
    expect(opensList("a")).toBe(false);
  });
});
