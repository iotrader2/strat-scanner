import type { Tf, TfState } from "../api";

const STRAT_CLASS: Record<string, string> = { "1": "s1", "2U": "s2u", "2D": "s2d", "3": "s3" };

export function TfBadge({ tf, state }: { tf: Tf; state: TfState | null | undefined }) {
  if (!state) return <span className="tf-badge empty">{tf}</span>;
  const strat = state.strat ?? "–";
  const title = `${tf}: Strat ${strat}, ${state.color} vs open ${state.open.toFixed(2)}${
    state.hammer ? ", hammer" : ""
  }${state.inside ? ", inside bar" : ""}`;
  return (
    <span className={`tf-badge ${state.color} ${STRAT_CLASS[strat] ?? ""}`} title={title}>
      <span className="tf-label">{tf}</span>
      <span className="tf-strat">{strat}</span>
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

export function ScorePill({ score }: { score: number }) {
  const level = score >= 70 ? "hi" : score >= 50 ? "mid" : "lo";
  return <span className={`score-pill ${level}`}>{score.toFixed(0)}</span>;
}

export function Legend() {
  return (
    <div className="legend">
      <span className="tf-badge green s1"><span className="tf-label">1</span>inside</span>
      <span className="tf-badge green s2u"><span className="tf-label">2U</span>broke high</span>
      <span className="tf-badge red s2d"><span className="tf-label">2D</span>broke low</span>
      <span className="tf-badge green s3"><span className="tf-label">3</span>outside</span>
      <span className="legend-note">Badge fill = continuity (green/red vs period open) · H = hammer</span>
    </div>
  );
}
