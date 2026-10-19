import { useEffect, useMemo, useRef } from "react";
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  createChart,
  createSeriesMarkers,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";
import type { ChartCandle } from "../api";
import { CHART_AVERAGES, sma } from "../movingAverage";

interface Props {
  candles: ChartCandle[];
  height?: number;
  visibleBars?: number;
  compact?: boolean;
  /** Simple moving averages of close, drawn across the candles. */
  averages?: readonly { period: number; color: string }[];
}

export function CandleChart({ candles, height = 420, visibleBars = 60, compact = false, averages }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const lines = useMemo(
    () => (averages ?? CHART_AVERAGES).filter((average) => candles.length >= average.period + 1),
    [averages, candles],
  );

  useEffect(() => {
    const el = ref.current;
    if (!el || candles.length === 0) return;

    const chart = createChart(el, {
      height,
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#8b93a7",
        fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
        fontSize: compact ? 10 : 12,
        attributionLogo: !compact,
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.03)" },
        horzLines: { color: "rgba(255,255,255,0.05)" },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "rgba(255,255,255,0.08)" },
      timeScale: { borderColor: "rgba(255,255,255,0.08)", rightOffset: compact ? 2 : 6 },
      handleScroll: !compact,
      handleScale: !compact,
    });

    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#22c55e",
      downColor: "#f43f5e",
      borderUpColor: "#22c55e",
      borderDownColor: "#f43f5e",
      wickUpColor: "#22c55e",
      wickDownColor: "#f43f5e",
      priceLineVisible: false,
    });
    series.setData(
      candles.map((c) => ({ time: c.time as Time, open: c.open, high: c.high, low: c.low, close: c.close })),
    );

    for (const average of lines) {
      const points = sma(candles, average.period);
      if (points.length < 2) continue;
      const line = chart.addSeries(LineSeries, {
        color: average.color,
        lineWidth: compact ? 1 : 2,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      line.setData(points.map((p) => ({ time: p.time as Time, value: p.value })));
    }

    if (!compact) {
      const volume = chart.addSeries(HistogramSeries, {
        priceFormat: { type: "volume" },
        priceScaleId: "vol",
        color: "rgba(139,147,167,0.25)",
        priceLineVisible: false,
        lastValueVisible: false,
      });
      chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
      volume.setData(
        candles.map((c) => ({
          time: c.time as Time,
          value: c.volume,
          color: c.close >= c.open ? "rgba(34,197,94,0.25)" : "rgba(244,63,94,0.25)",
        })),
      );
    }

    // Only two marker kinds, to keep the candles readable: H = hammer, I = inside bar (Strat 1).
    const markers: SeriesMarker<Time>[] = [];
    for (const c of compact ? candles : candles.slice(-visibleBars)) {
      const time = c.time as Time;
      if (c.hammer && !compact) {
        markers.push({ time, position: "belowBar", shape: "arrowUp", color: "#38bdf8", text: "H" });
      }
      if (c.strat === "1") {
        markers.push({ time, position: "belowBar", shape: "arrowUp", color: "#facc15", text: "I", size: compact ? 0.7 : 1 });
      }
    }
    createSeriesMarkers(series, markers);

    const visible = Math.min(candles.length, visibleBars);
    chart.timeScale().setVisibleLogicalRange({ from: candles.length - visible - 0.5, to: candles.length + (compact ? 1 : 4) });

    return () => chart.remove();
  }, [candles, height, visibleBars, compact, lines]);

  return (
    <div className="chart-block">
      {lines.length > 0 && (
        <div className="ma-legend" title="Simple moving averages of the candles on this chart">
          {lines.map((average) => (
            <span key={average.period}>
              <i style={{ background: average.color }} />
              {average.period}
            </span>
          ))}
        </div>
      )}
      <div ref={ref} className="chart" style={{ height }} />
    </div>
  );
}
