import { useEffect, useRef } from "react";
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";
import type { ChartCandle } from "../api";

export interface PriceLine {
  price: number;
  color: string;
  title: string;
}

interface Props {
  candles: ChartCandle[];
  lines?: PriceLine[];
  height?: number;
  visibleBars?: number;
  compact?: boolean;
}

export function CandleChart({ candles, lines = [], height = 420, visibleBars = 60, compact = false }: Props) {
  const ref = useRef<HTMLDivElement>(null);

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
    });
    series.setData(
      candles.map((c) => ({ time: c.time as Time, open: c.open, high: c.high, low: c.low, close: c.close })),
    );

    if (!compact) {
      const volume = chart.addSeries(HistogramSeries, {
        priceFormat: { type: "volume" },
        priceScaleId: "vol",
        color: "rgba(139,147,167,0.25)",
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

    if (!compact) {
      const hammers: SeriesMarker<Time>[] = candles
        .slice(-visibleBars)
        .filter((c) => c.hammer)
        .map((c) => ({ time: c.time as Time, position: "belowBar", shape: "arrowUp", color: "#38bdf8", text: "H" }));
      createSeriesMarkers(series, hammers);
    }

    for (const line of lines) {
      series.createPriceLine({
        price: line.price,
        color: line.color,
        lineWidth: 2,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: compact ? "" : line.title,
      });
    }

    const visible = compact ? candles.length : Math.min(candles.length, visibleBars);
    chart.timeScale().setVisibleLogicalRange({ from: candles.length - visible - 0.5, to: candles.length + (compact ? 1 : 4) });

    return () => chart.remove();
  }, [candles, lines, height, visibleBars, compact]);

  return <div ref={ref} className="chart" style={{ height }} />;
}
