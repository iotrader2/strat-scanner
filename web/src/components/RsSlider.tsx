interface Props {
  value: number;
  min: number;
  max: number;
  onChange: (v: number) => void;
}

/** Linear 1-step slider for the minimum relative-strength percentile, styled like the Min price / volume sliders. */
export function RsSlider({ value, min, max, onChange }: Props) {
  return (
    <label className="slider-field">
      <span className="slider-head">
        Min RS
        <span className="slider-readout">≥ P{value}</span>
      </span>
      <input
        type="range"
        className="log-slider"
        min={min}
        max={max}
        step={1}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-label="Min RS percentile"
      />
      <span className="slider-scale">
        <span>P{min}</span>
        <span>P{max}</span>
      </span>
    </label>
  );
}
