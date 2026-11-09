interface Props {
  label: string;
  value: [number, number];
  min: number;
  max: number;
  step?: number;
  /** How a value reads in the header and the scale, e.g. (v) => `P${v}`. */
  format?: (v: number) => string;
  onChange: (v: [number, number]) => void;
}

/** Two-handle min / max range, styled like the ATR % slider. The full range means no filter. */
export function RangeSlider({ label, value, min, max, step = 1, format = String, onChange }: Props) {
  const [lo, hi] = value;
  const span = max - min || 1;
  const left = ((lo - min) / span) * 100;
  const right = ((hi - min) / span) * 100;
  const readout = lo <= min && hi >= max ? "Any" : `${format(lo)} – ${format(hi)}`;
  return (
    <div className="field slider-field range-slider" role="group" aria-label={`${label} range`}>
      <span className="slider-head">
        {label}
        <span className="slider-readout">{readout}</span>
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
          onChange={(e) => onChange([Math.min(Number(e.target.value), hi), hi])}
          aria-label={`Min ${label}`}
        />
        <input
          type="range"
          className="log-slider range-thumb"
          min={min}
          max={max}
          step={step}
          value={hi}
          onChange={(e) => onChange([lo, Math.max(Number(e.target.value), lo)])}
          aria-label={`Max ${label}`}
        />
      </div>
      <span className="slider-scale">
        <span>{format(min)}</span>
        <span>{format(max)}</span>
      </span>
    </div>
  );
}
