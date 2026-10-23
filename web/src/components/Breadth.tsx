import type { Breadth } from "../api";
import { adRatio, nasiRead, universeLabel } from "../market";
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

function CountBar({
  green,
  greenLabel,
  red,
  redLabel,
  gray = 0,
  grayTitle,
  label,
  ratio,
}: {
  green: number;
  greenLabel: string;
  red: number;
  redLabel: string;
  gray?: number;
  grayTitle?: string;
  /** Row name on the left ("Universe", "Nasdaq") when a card stacks more than one bar. */
  label?: string;
  /** Show "(1.3 to 1)" for the leading side, colored like that side. */
  ratio?: boolean;
}) {
  const total = green + red + gray;
  const width = (n: number) => (total > 0 ? `${(n / total) * 100}%` : "0%");
  const lead = ratio ? adRatio(green, red) : null;
  return (
    <div className="ad-row">
      <div className={`ad-head${label ? " labeled" : ""}`}>
        {label && <span className="ad-label">{label}</span>}
        <span className="muted">
          <span className="green-text">
            {green.toLocaleString()} {greenLabel}
          </span>
          {" · "}
          <span className="red-text">
            {red.toLocaleString()} {redLabel}
          </span>
          {lead && (
            <>
              {" "}
              <span className={lead.decliners ? "red-text" : "green-text"}>({lead.text})</span>
            </>
          )}
        </span>
      </div>
      <div className="ad-track" title={grayTitle}>
        <span className="ad-adv" style={{ width: width(green) }} />
        {gray > 0 && <span className="ad-unch" style={{ width: width(gray) }} />}
        <span className="ad-dec" style={{ width: width(red) }} />
      </div>
    </div>
  );
}

/** $NASI line, Fear & Greed gauge, and breadth of the symbols the scanner tracks. */
export function BreadthPanel({ breadth }: { breadth: Breadth }) {
  const nasi = breadth.nasi;
  const nasiCall = nasi && nasi.points.length > 0 ? nasiRead(nasi) : null;
  const fear = breadth.fear_greed;
  const issues = breadth.issues;
  const nasdaq = breadth.nasdaq_issues ?? null;
  const extremes = breadth.highs_lows;
  const nasdaqExtremes = breadth.nasdaq_highs_lows ?? null;
  if (!nasi && !fear && !issues && !nasdaq && !extremes && !nasdaqExtremes) return null;

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
          <LineChart points={nasi.points} color={nasi.value >= 0 ? "#22c55e" : "#f43f5e"} height={220} fill />
        </div>
      )}
      {(fear || issues || nasdaq || extremes || nasdaqExtremes) && (
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
          {(issues || nasdaq) && (
            <div className="card breadth-card">
              <div className="breadth-head">
                <div>
                  <div className="sym">Advancers vs decliners</div>
                  <div className="sub muted">Today{issues ? ` · ${universeLabel(issues.names)}` : ""}</div>
                </div>
              </div>
              {issues && (
                <CountBar
                  label={nasdaq ? "Universe" : undefined}
                  green={issues.advancing}
                  greenLabel="up"
                  red={issues.declining}
                  redLabel="down"
                  gray={issues.unchanged}
                  grayTitle={`${issues.unchanged.toLocaleString()} unchanged`}
                  ratio={Boolean(nasdaq)}
                />
              )}
              {nasdaq && (
                <CountBar
                  label="Nasdaq"
                  green={nasdaq.advancing}
                  greenLabel="up"
                  red={nasdaq.declining}
                  redLabel="down"
                  gray={nasdaq.unchanged}
                  grayTitle={`All Nasdaq issues · ${nasdaq.unchanged.toLocaleString()} unchanged · WSJ markets diary, ${nasdaq.as_of}`}
                  ratio
                />
              )}
            </div>
          )}
          {(extremes || nasdaqExtremes) && (
            <div className="card breadth-card">
              <div className="breadth-head">
                <div>
                  <div className="sym">New highs vs new lows</div>
                  <div className="sub muted">52-week{extremes ? ` · ${universeLabel(extremes.names)}` : ""}</div>
                </div>
              </div>
              {extremes && (
                <CountBar
                  label={nasdaqExtremes ? "Universe" : undefined}
                  green={extremes.highs}
                  greenLabel={extremes.highs === 1 ? "high" : "highs"}
                  red={extremes.lows}
                  redLabel={extremes.lows === 1 ? "low" : "lows"}
                  grayTitle="Latest session versus the prior 252 sessions"
                  ratio={Boolean(nasdaqExtremes)}
                />
              )}
              {nasdaqExtremes && (
                <CountBar
                  label="Nasdaq"
                  green={nasdaqExtremes.highs}
                  greenLabel={nasdaqExtremes.highs === 1 ? "high" : "highs"}
                  red={nasdaqExtremes.lows}
                  redLabel={nasdaqExtremes.lows === 1 ? "low" : "lows"}
                  grayTitle={`All Nasdaq issues at a 52-week high or low · WSJ markets diary, ${nasdaqExtremes.as_of}`}
                  ratio
                />
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
