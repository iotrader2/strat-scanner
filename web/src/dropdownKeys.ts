/** What a key press does to an open listbox: move the highlight, choose it, close, or nothing. */
export type ListAction =
  | { type: "move"; index: number }
  | { type: "select"; index: number }
  | { type: "close" }
  | { type: "none" };

/** Keyboard behaviour of an open dropdown list (WAI-ARIA listbox pattern plus type-to-jump). */
export function listKeyAction(key: string, active: number, labels: string[]): ListAction {
  const count = labels.length;
  if (count === 0) return key === "Escape" || key === "Tab" ? { type: "close" } : { type: "none" };
  switch (key) {
    case "ArrowDown":
      return { type: "move", index: Math.min(active + 1, count - 1) };
    case "ArrowUp":
      return { type: "move", index: Math.max(active - 1, 0) };
    case "Home":
    case "PageUp":
      return { type: "move", index: 0 };
    case "End":
    case "PageDown":
      return { type: "move", index: count - 1 };
    case "Enter":
    case " ":
      return { type: "select", index: active };
    case "Escape":
    case "Tab":
      return { type: "close" };
  }
  if (key.length === 1 && /\S/.test(key)) {
    const ch = key.toLowerCase();
    for (let step = 1; step <= count; step++) {
      const i = (active + step) % count;
      if (labels[i].toLowerCase().startsWith(ch)) return { type: "move", index: i };
    }
  }
  return { type: "none" };
}

/** Keys that open a closed dropdown from its trigger button. */
export function opensList(key: string): boolean {
  return key === "ArrowDown" || key === "ArrowUp" || key === "Enter" || key === " ";
}
