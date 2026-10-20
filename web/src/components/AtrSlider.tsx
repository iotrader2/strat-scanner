import { ATR_PCT_RANGE, formatAtrRange, normalizeAtrRange, type AtrRange } from "../atrFilter";

interface Props {
  value: AtrRange;
  onChange: (v: AtrRange) => void;
}

/** Two-handle ATR % range, styled like the Min price / volume sliders. The right end means no upper limit. */
export function AtrSlider({ value, onChange }: Props) {
  const [lo, hi] = value;
  const { min, max, step } = ATR_PCT_RANGE;
  const span = max - min;
  const left = ((lo - min) / span) * 100;
  const right = ((hi - min) / span) * 100;
  return (
    <div className="field slider-field atr-slider" role="group" aria-label="ATR % range">
      <span className="slider-head">
        ATR %
        <span className="slider-readout">{formatAtrRange(value)}</span>
      </span>
      <div className="range-track">
        <div
          className="range-fill"
          style={{
            background: `linear-gradient(90deg, rgba(148,163,184,0.25) ${left}%, rgba(56,189,248,0.6) ${left}%, rgba(167,139,250,0.6) ${right}%, rgba(148,163,184,0.25) ${right}%)`,
          }}
        />
        <input
          type="range"
          className="log-slider range-thumb"
          min={min}
          max={max}
          step={step}
          value={lo}
          onChange={(e) => onChange(normalizeAtrRange([Math.min(Number(e.target.value), hi), hi]))}
          aria-label="Min ATR %"
        />
        <input
          type="range"
          className="log-slider range-thumb"
          min={min}
          max={max}
          step={step}
          value={hi}
          onChange={(e) => onChange(normalizeAtrRange([lo, Math.max(Number(e.target.value), lo)]))}
          aria-label="Max ATR %"
        />
      </div>
      <span className="slider-scale">
        <span>{min}%</span>
        <span>{max}%+</span>
      </span>
    </div>
  );
}
