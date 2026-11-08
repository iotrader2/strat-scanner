/** The Stock Scanner's Type filter: which kinds of names are listed. */
export type Kind = "all" | "stock" | "etf" | "inverse" | "stock_inverse";

export const KIND_LABELS: Record<Kind, string> = {
  all: "Stocks + ETFs",
  stock: "Stocks",
  etf: "ETFs",
  inverse: "Inverse ETFs",
  stock_inverse: "Stocks + Inverse ETFs",
};

export const KINDS = Object.keys(KIND_LABELS) as Kind[];

export const isKind = (v: unknown): v is Kind => typeof v === "string" && v in KIND_LABELS;

type Row = { kind: string; indexes?: string };

/** 1x inverse ETF (the backend's "inverse" ETF group, e.g. SH, PSQ, MUD, TSLQ, AMZD). */
export const isInverseEtf = (r: Row): boolean => r.kind === "etf" && r.indexes === "inverse";

/** Whether a row passes the Type filter. "ETFs" includes the inverse ETFs. */
export function matchesKind(r: Row, kind: Kind): boolean {
  switch (kind) {
    case "all":
      return true;
    case "stock":
      return r.kind === "stock";
    case "etf":
      return r.kind === "etf";
    case "inverse":
      return isInverseEtf(r);
    case "stock_inverse":
      return r.kind === "stock" || isInverseEtf(r);
  }
}
