import { useState } from "react";
import { SLIDER_STEPS, sliderValue, syncSliderPosition, valueToSlider } from "../logScale";

interface Props {
  label: string;
  value: number;
  min: number;
  max: number;
  format: (v: number) => string;
  onChange: (v: number) => void;
}

export function LogSlider({ label, value, min, max, format, onChange }: Props) {
  const [pos, setPos] = useState(() => valueToSlider(value, min, max));
  const shown = syncSliderPosition(value, min, max, pos);
  return (
    <label className="slider-field">
      <span className="slider-head">
        {label}
        <span className="slider-readout">≥ {format(value)}</span>
      </span>
      <input
        type="range"
        className="log-slider"
        min={0}
        max={SLIDER_STEPS}
        step={1}
        value={shown}
        onChange={(e) => {
          const next = Number(e.target.value);
          setPos(next);
          onChange(sliderValue(next, min, max));
        }}
        aria-label={label}
      />
      <span className="slider-scale">
        <span>{format(min)}</span>
        <span>{format(max)}</span>
      </span>
    </label>
  );
}
