import type { Breadth, IssueCounts } from "../api";
import { nasiRead } from "../market";
import { LineChart } from "./LineChart";

function signed(value: number, digits = 0): string {
  const text = value.toFixed(digits);
  return value > 0 ? `+${text}` : text;
}

function FearGreedBar({ score, rating }: { score: number; rating: string }) {
  const pct = Math.min(100, Math.max(0, score));
  return (
    <div className="fg">
      <div className="fg-track">
        <span className="fg-marker" style={{ left: `${pct}%` }} />
      </div>
      <div className="fg-scale">
        <span>Extreme fear</span>
        <span>Neutral</span>
        <span>Extreme greed</span>
      </div>
      <div className="fg-readout">
        <b>{Math.round(score)}</b>
        <span className="muted">{rating}</span>
      </div>
    </div>
  );
}

function IssueBar({ label, counts }: { label: string; counts: IssueCounts }) {
  const total = counts.advancing + counts.declining + counts.unchanged;
  if (total <= 0) return null;
  const width = (n: number) => `${(n / total) * 100}%`;
  return (
    <div className="ad-row">
      <div className="ad-head">
        <span>{label}</span>
        <span className="muted">
          <span className="green-text">{counts.advancing.toLocaleString()} up</span>
          {" · "}
          <span className="red-text">{counts.declining.toLocaleString()} down</span>
        </span>
      </div>
      <div className="ad-track" title={`${counts.unchanged.toLocaleString()} unchanged`}>
        <span className="ad-adv" style={{ width: width(counts.advancing) }} />
        <span className="ad-unch" style={{ width: width(counts.unchanged) }} />
        <span className="ad-dec" style={{ width: width(counts.declining) }} />
      </div>
    </div>
  );
}

/** $NASI line, Fear & Greed gauge and advancers vs decliners. Missing sources are left out. */
export function BreadthPanel({ breadth }: { breadth: Breadth }) {
  const nasi = breadth.nasi;
  const nasiCall = nasi && nasi.points.length > 0 ? nasiRead(nasi) : null;
  const fear = breadth.fear_greed;
  const issues = breadth.issues;
  const hasIssues = Boolean(issues && (issues.nasdaq || issues.nyse));
  if (!nasi && !fear && !hasIssues) return null;

  return (
    <section className="breadth-grid">
      {nasi && nasi.points.length > 0 && (
        <div className="card breadth-card">
          <div className="breadth-head">
            <div>
              <div className="sym">$NASI</div>
              <div className={`sub ${nasiCall?.tone === "bad" ? "red-text" : nasiCall?.tone === "good" ? "green-text" : ""}`}>
                {nasiCall?.call}
              </div>
            </div>
            <div className="sector-right">
              <span className={`num ${nasi.value >= 0 ? "green-text" : "red-text"}`}>{signed(nasi.value, 0)}</span>
              {nasi.change !== null && (
                <span className={`small ${nasi.change >= 0 ? "green-text" : "red-text"}`}>{signed(nasi.change, 0)}</span>
              )}
            </div>
          </div>
          <p className="nasi-note muted">{nasiCall?.detail}</p>
          <LineChart points={nasi.points} color={nasi.value >= 0 ? "#22c55e" : "#f43f5e"} height={220} />
        </div>
      )}
      {(fear || hasIssues) && (
        <div className="breadth-side">
          {fear && (
            <div className="card breadth-card">
              <div className="breadth-head">
                <div>
                  <div className="sym">Fear &amp; Greed</div>
                  <div className="sub muted">CNN index</div>
                </div>
              </div>
              <FearGreedBar score={fear.score} rating={fear.rating} />
              <div className="fg-history muted">
                {fear.previous_close !== null && <span>Yesterday {Math.round(fear.previous_close)}</span>}
                {fear.previous_week !== null && <span>1W {Math.round(fear.previous_week)}</span>}
                {fear.previous_month !== null && <span>1M {Math.round(fear.previous_month)}</span>}
              </div>
            </div>
          )}
          {hasIssues && issues && (
            <div className="card breadth-card">
              <div className="breadth-head">
                <div>
                  <div className="sym">Advancers vs decliners</div>
                  <div className="sub muted">Issues today</div>
                </div>
              </div>
              {issues.nasdaq && <IssueBar label="Nasdaq" counts={issues.nasdaq} />}
              {issues.nyse && <IssueBar label="NYSE" counts={issues.nyse} />}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
