import type { HigherTf, Tf, TfState } from "../api";

const STRAT_CLASS: Record<string, string> = { "1": "s1", "2U": "s2u", "2D": "s2d", "3": "s3" };
const STRAT_LABEL: Record<string, string> = { "1": "INSIDE", "2U": "UP", "2D": "DOWN", "3": "OUTSIDE" };

/** Badge color = Continuity: the bar in progress when the scan sent it, else the last completed bar. */
export function badgeContinuity(state: TfState): { color: TfState["color"]; open: number; live: boolean } {
  if (state.live_color && state.live_open != null) return { color: state.live_color, open: state.live_open, live: true };
  return { color: state.color, open: state.open, live: false };
}

export function TfBadge({ tf, state }: { tf: Tf | HigherTf; state: TfState | null | undefined }) {
  if (!state) return <span className="tf-badge empty">{tf}</span>;
  const strat = state.strat ?? "–";
  const { color, open, live } = badgeContinuity(state);
  const title = `${tf}: Strat ${strat} (last completed bar), ${color} vs open ${open.toFixed(2)}${live ? " (bar in progress)" : ""}${
    state.hammer ? ", hammer" : ""
  }${state.inside ? ", inside bar" : ""}`;
  return (
    <span className={`tf-badge ${color} ${STRAT_CLASS[strat] ?? ""}`} title={title}>
      <span className="tf-label">{tf}</span>
      <span className="tf-strat">{STRAT_LABEL[strat] ?? strat}</span>
      {state.hammer && <span className="tf-flag" title="Hammer">H</span>}
    </span>
  );
}

export function TfBadges({
  tf,
  frames = ["D", "W", "M"],
}: {
  tf: Partial<Record<Tf | HigherTf, TfState | null>>;
  frames?: readonly (Tf | HigherTf)[];
}) {
  return (
    <span className="tf-badges">
      {frames.map((t) => (
        <TfBadge key={t} tf={t} state={tf[t]} />
      ))}
    </span>
  );
}

export function Legend() {
  return (
    <div className="legend">
      <span className="tf-badge green s1"><span className="tf-strat">INSIDE</span></span>
      <span className="tf-badge green s2u"><span className="tf-strat">UP</span>broke high</span>
      <span className="tf-badge red s2d"><span className="tf-strat">DOWN</span>broke low</span>
      <span className="tf-badge green s3"><span className="tf-strat">OUTSIDE</span></span>
      <span className="tf-badge flat" title="Hammer: a small H on any Strat badge">
        <span className="tf-flag">H</span>
        <span className="tf-strat">hammer</span>
      </span>
    </div>
  );
}

export { ScorePill } from "./ScoreBreakdown";

/** Marks symbols outside the S&P 500 / Nasdaq-100 / ETF universe that were added from the watchlist. */
export function AddedChip() {
  return (
    <span className="added-chip">
      Added
    </span>
  );
}
