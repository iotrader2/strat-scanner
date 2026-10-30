import { useEffect, useRef } from "react";
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  TickMarkType,
  createChart,
  type Time,
} from "lightweight-charts";
import type { IntradayBar } from "../api";
import { VOLUME_BASE_COLOR } from "../macd";
import {
  INTRADAY_EMAS,
  INTRADAY_HEIGHT,
  INTRADAY_VISIBLE_BARS,
  formatIntradayDay,
  formatIntradayTime,
  intradayLegendTitle,
  intradayPlot,
  intradaySessionNote,
} from "../intradayChart";

interface Props {
  bars: IntradayBar[];
  height?: number;
  /** Latest bars kept on screen. Older bars in ``bars`` stay available by scrolling. */
  visibleBars?: number;
  /** Sessions the server loaded (the scrollable range). */
  displaySessions?: number;
  /** Sessions of history the 120 EMA was seeded on. */
  seedSessions?: number;
}

/**
 * 15-minute candles, volume, and the server-computed EMAs.
 * Same library, candle colors, grid, and volume overlay as the daily chart. No MACD pane:
 * this chart's overlays are the 6, 20, 50, and 120 EMAs.
 */
export function IntradayChart({
  bars,
  height = INTRADAY_HEIGHT,
  visibleBars = INTRADAY_VISIBLE_BARS,
  displaySessions = 10,
  seedSessions = 30,
}: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || bars.length === 0) return;

    const plot = intradayPlot(bars);
    const realTime = (time: Time) => (typeof time === "number" ? plot.clock.get(time) : undefined);
    const chart = createChart(el, {
      height,
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#8b93a7",
        fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
        fontSize: 12,
        attributionLogo: true,
      },
      localization: {
        timeFormatter: (time: Time) => {
          const real = realTime(time);
          return real == null ? "" : formatIntradayTime(real, true);
        },
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.03)" },
        horzLines: { color: "rgba(255,255,255,0.05)" },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "rgba(255,255,255,0.08)" },
      timeScale: {
        borderColor: "rgba(255,255,255,0.08)",
        rightOffset: 6,
        secondsVisible: false,
        tickMarkFormatter: (time: Time, tickMarkType: TickMarkType) => {
          const real = realTime(time);
          if (real == null) return "";
          if (tickMarkType === TickMarkType.Time || tickMarkType === TickMarkType.TimeWithSeconds) {
            return formatIntradayTime(real, false);
          }
          return formatIntradayDay(real);
        },
      },
      handleScroll: true,
      handleScale: true,
    });

    const candles = chart.addSeries(CandlestickSeries, {
      upColor: "#22c55e",
      downColor: "#f43f5e",
      borderUpColor: "#22c55e",
      borderDownColor: "#f43f5e",
      wickUpColor: "#22c55e",
      wickDownColor: "#f43f5e",
      priceLineVisible: false,
    });
    candles.setData(plot.candles.map((bar) => ({ ...bar, time: bar.time as Time })));

    for (const line of plot.lines) {
      if (line.points.length < 2) continue;
      const series = chart.addSeries(LineSeries, {
        color: line.color,
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      series.setData(line.points.map((point) => ({ time: point.time as Time, value: point.value })));
    }

    const volume = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "vol",
      color: VOLUME_BASE_COLOR,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    volume.setData(plot.volume.map((bar) => ({ time: bar.time as Time, value: bar.value, color: bar.color })));

    const visible = Math.min(bars.length, visibleBars);
    chart.timeScale().setVisibleLogicalRange({ from: bars.length - visible - 0.5, to: bars.length + 4 });

    return () => chart.remove();
  }, [bars, height, visibleBars]);

  if (bars.length === 0) {
    return <p className="muted small">No 15-minute bars for this symbol yet.</p>;
  }

  return (
    <div className="chart-block">
      <div className="ma-legend">
        <span className="ma-group" title={intradayLegendTitle(seedSessions)}>
          <span className="ma-kind">EMA</span>
          {INTRADAY_EMAS.map((average) => (
            <span key={average.period}>
              <i style={{ background: average.color }} />
              {average.period}
            </span>
          ))}
        </span>
        <span className="intraday-note">{intradaySessionNote(displaySessions)}</span>
      </div>
      <div ref={ref} className="chart" style={{ height }} />
    </div>
  );
}
