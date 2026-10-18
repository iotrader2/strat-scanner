import type { ScanRow } from "./api";
import { fmtRs } from "./leadership";

/** Smaller moves than this many percentile points are not shown on the chip. */
export const RS_CHANGE_MIN = 3;
/** Sessions between the two RS readings (backend `RS_LOOKBACK`). */
export const RS_LOOKBACK_SESSIONS = 5;
/** A breakdown or leader transition stays marked NEW for this many sessions (backend `STATE_LOOKBACK`). */
export const NEW_SESSIONS = 3;

export type RsChangeFields = Pick<ScanRow, "rs"> & {
  rs_prev?: number | null;
  rs_prev_date?: string | null;
  rs_change?: number | null;
};

export interface RsDelta {
  points: number;
  dir: "up" | "down";
  /** "▼7" / "▲12" */
  text: string;
}

/** The RS change to show on the chip: null when unknown or smaller than `RS_CHANGE_MIN` points. */
export function rsDelta(r: Pick<RsChangeFields, "rs_change">, min: number = RS_CHANGE_MIN): RsDelta | null {
  const c = r.rs_change;
  if (c === null || c === undefined || Math.abs(c) < min) return null;
  return c < 0 ? { points: c, dir: "down", text: `▼${-c}` } : { points: c, dir: "up", text: `▲${c}` };
}

export type NewKind = "warning" | "broken" | "leader";

export interface NewMarker {
  kind: NewKind;
  /** The word after NEW on the chip. */
  label: string;
  since: string;
}

type NewFields = { leadership?: Pick<ScanRow["leadership"], "breakdown"> & Partial<Pick<ScanRow["leadership"], "breakdown_new" | "leader_new">> };

/** The transition to mark NEW: a breakdown that just worsened comes first, else a leader that just crossed the RS gate. */
export function newMarker(r: NewFields): NewMarker | null {
  const b = r.leadership?.breakdown_new;
  if (b) return { kind: b.to, label: b.to === "broken" ? "broken" : "weakening", since: b.since };
  const l = r.leadership?.leader_new;
  if (l) return { kind: "leader", label: "leader", since: l.since };
  return null;
}

const sessionsText = (n: number) => (n === 0 ? "today" : n === 1 ? "1 session ago" : `${n} sessions ago`);

/** Tooltip text: the RS percentile, its change vs a week ago, the NEW transition with its date, and the breakdown reasons. */
export function rsTitle(r: RsChangeFields & NewFields): string {
  const reasons = (r.leadership as ScanRow["leadership"] | undefined)?.breakdown_reasons ?? [];
  const lines = [`Relative strength ${fmtRs(r.rs)}: blended 1M/3M/6M return percentile${reasons.length ? `. ${reasons.join("; ")}` : ""}`];
  const c = r.rs_change;
  if (c !== null && c !== undefined && r.rs_prev !== null && r.rs_prev !== undefined) {
    const shown = rsDelta(r);
    const move = shown ? shown.text : c === 0 ? "unchanged" : `${c > 0 ? "+" : "-"}${Math.abs(c)}, under ${RS_CHANGE_MIN} points so not shown`;
    const when = r.rs_prev_date ? ` on ${r.rs_prev_date}` : "";
    lines.push(`RS change vs ${RS_LOOKBACK_SESSIONS} sessions ago: ${fmtRs(r.rs_prev)}${when} → ${fmtRs(r.rs)} (${move})`);
  }
  const b = r.leadership?.breakdown_new;
  const l = r.leadership?.leader_new;
  if (b) {
    const to = b.to === "broken" ? "broken" : "weakening";
    const from = b.from === "warning" ? "weakening" : "no breakdown flag";
    lines.push(`NEW ${to}: changed on ${b.since} (${sessionsText(b.sessions_ago)}), from ${from}. Marked new for ${NEW_SESSIONS} sessions.`);
  }
  if (l) {
    lines.push(
      `NEW leader: RS crossed above P90 on ${l.since} (${sessionsText(l.sessions_ago)}), from ${fmtRs(l.from_rs)}. Marked new for ${NEW_SESSIONS} sessions.`,
    );
  }
  return lines.join("\n");
}

export interface RsChipView {
  level: "none" | "warning" | "broken";
  delta: RsDelta | null;
  newMarker: NewMarker | null;
  /** The usual breakdown flag ("weakening" / "broken"), left out when the NEW marker already says it. */
  flag: string;
  kill: string;
  title: string;
}

/** Everything the chip shows (the change, not the RS value itself, which is in the tooltip); null when the symbol has no RS yet. */
export function rsChipView(row: ScanRow): RsChipView | null {
  if (row.rs === null || row.rs === undefined) return null;
  const level = row.leadership?.breakdown ?? "none";
  const marker = newMarker(row);
  const flag = level === "broken" ? "broken" : level === "warning" ? "weakening" : "";
  const kill = row.kill_candle && row.kill_candle.penalty > 0 ? ` · kill candle ${row.kill_candle.date.slice(5)}` : "";
  return {
    level,
    delta: rsDelta(row),
    newMarker: marker,
    flag: marker && marker.kind !== "leader" ? "" : flag,
    kill,
    title: rsTitle(row),
  };
}
