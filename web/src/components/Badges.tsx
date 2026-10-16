import type { Tf, TfState } from "../api";

const STRAT_CLASS: Record<string, string> = { "1": "s1", "2U": "s2u", "2D": "s2d", "3": "s3" };
const STRAT_LABEL: Record<string, string> = { "1": "INSIDE", "2U": "UP", "3": "OUTSIDE" };

export function TfBadge({ tf, state }: { tf: Tf; state: TfState | null | undefined }) {
  if (!state) return <span className="tf-badge empty">{tf}</span>;
  const strat = state.strat ?? "–";
  const title = `${tf}: Strat ${strat}, ${state.color} vs open ${state.open.toFixed(2)}${
    state.hammer ? ", hammer" : ""
  }${state.inside ? ", inside bar" : ""}`;
  return (
    <span className={`tf-badge ${state.color} ${STRAT_CLASS[strat] ?? ""}`} title={title}>
      <span className="tf-label">{tf}</span>
      <span className="tf-strat">{STRAT_LABEL[strat] ?? strat}</span>
      {state.hammer && <span className="tf-flag" title="Hammer">H</span>}
    </span>
  );
}

export function TfBadges({ tf }: { tf: Record<Tf, TfState | null> }) {
  return (
    <span className="tf-badges">
      {(["M", "W", "D"] as Tf[]).map((t) => (
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
      <span className="tf-badge red s2d">broke low</span>
      <span className="tf-badge green s3"><span className="tf-strat">OUTSIDE</span></span>
      <span className="legend-note">Badge fill = continuity (green/red vs period open) · H = hammer</span>
    </div>
  );
}

export { ScorePill } from "./ScoreBreakdown";

/** Marks symbols outside the S&P 500 / Nasdaq-100 / ETF universe that were added from the watchlist. */
export function AddedChip() {
  return (
    <span className="added-chip" title="Added to the watchlist from outside the S&P 500 / Nasdaq-100 universe">
      Added
    </span>
  );
}
