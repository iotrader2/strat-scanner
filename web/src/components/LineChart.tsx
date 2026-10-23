import { useEffect, useRef } from "react";
import { ColorType, CrosshairMode, LineSeries, LineStyle, createChart, type Time } from "lightweight-charts";
import type { NasiPoint } from "../api";

/**
 * Compact line chart. A dashed zero line is drawn when the series crosses zero.
 * `fill`: grow to the parent's free height (a flex column), with `height` as the minimum. The chart auto-sizes.
 */
export function LineChart({ points, color, height = 220, fill = false }: { points: NasiPoint[]; color: string; height?: number; fill?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || points.length === 0) return;

    const chart = createChart(el, {
      height,
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#8b93a7",
        fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
        fontSize: 10,
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.03)" },
        horzLines: { color: "rgba(255,255,255,0.05)" },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "rgba(255,255,255,0.08)" },
      timeScale: { borderColor: "rgba(255,255,255,0.08)", rightOffset: 2 },
      handleScroll: false,
      handleScale: false,
    });

    const series = chart.addSeries(LineSeries, {
      color,
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
    });
    series.setData(points.map((p) => ({ time: p.time as Time, value: p.value })));
    const values = points.map((p) => p.value);
    if (Math.min(...values) < 0 && Math.max(...values) > 0) {
      series.createPriceLine({
        price: 0,
        color: "rgba(139,147,167,0.7)",
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: "",
      });
    }
    chart.timeScale().fitContent();

    return () => chart.remove();
  }, [points, color, height]);

  if (fill) return <div ref={ref} className="chart chart-fill" style={{ minHeight: height }} />;
  return <div ref={ref} className="chart" style={{ height }} />;
}
