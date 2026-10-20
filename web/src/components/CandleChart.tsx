import { useEffect, useMemo, useRef } from "react";
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";
import type { ChartCandle } from "../api";
import {
  MACD_COLORS,
  MACD_PANE,
  MACD_STRETCH,
  MACD_TOOLTIP,
  MACD_TRIGGER_COLOR,
  MACD_TRIGGER_NOTE,
  PRICE_PANE,
  VOLUME_BASE_COLOR,
  volumeBarColor,
  macdChartSeries,
} from "../macd";
import { CHART_AVERAGES, MA_LEGEND_TITLE, sma } from "../movingAverage";

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
  const macdPane = useMemo(() => macdChartSeries(candles), [candles]);

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
        panes: {
          enableResize: !compact,
          separatorColor: "rgba(255,255,255,0.08)",
          separatorHoverColor: "rgba(56,189,248,0.35)",
        },
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
        color: VOLUME_BASE_COLOR,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
      volume.setData(
        candles.map((c) => ({
          time: c.time as Time,
          value: c.volume,
          color: volumeBarColor(c.close, c.open),
        })),
      );
    }

    // Same chart instance, so the histogram pane shares the price chart's time scale and crosshair.
    let fitFrame = 0;
    if (macdPane) {
      const histogram = chart.addSeries(
        HistogramSeries,
        {
          priceLineVisible: false,
          lastValueVisible: false,
          priceFormat: { type: "price", precision: 2, minMove: 0.01 },
        },
        MACD_PANE,
      );
      histogram.setData(macdPane.histogram.map((p) => ({ time: p.time as Time, value: p.value, color: p.color })));
      createSeriesMarkers(
        histogram,
        macdPane.triggers.map((trigger) => ({
          time: trigger.time as Time,
          position: "atPriceBottom" as const,
          price: 0,
          shape: "arrowUp" as const,
          color: MACD_TRIGGER_COLOR,
          size: compact ? 0.8 : 1,
        })),
      );
      histogram.createPriceLine({
        price: 0,
        color: "rgba(139,147,167,0.55)",
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: false,
        title: "",
      });
      const fitMacdPane = () => {
        const macdPaneApi = chart.panes()[MACD_PANE];
        const priceHeight = chart.panes()[PRICE_PANE]?.getHeight() ?? 0;
        const macdHeight = macdPaneApi?.getHeight() ?? 0;
        const plot = priceHeight + macdHeight;
        if (!macdPaneApi || plot < 40) return;
        macdPaneApi.setHeight(Math.round(plot * (MACD_STRETCH / (1 + MACD_STRETCH))));
      };
      fitMacdPane();
      fitFrame = requestAnimationFrame(fitMacdPane);
      chart.priceScale("right", MACD_PANE).applyOptions({
        scaleMargins: { top: 0.12, bottom: 0.12 },
        borderColor: "rgba(255,255,255,0.08)",
      });
    }

    // H = hammer, I = inside bar (Strat 1), and a green arrow where the MACD histogram triggers.
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
    for (const trigger of macdPane?.triggers ?? []) {
      markers.push({
        time: trigger.time as Time,
        position: "belowBar",
        shape: "arrowUp",
        color: MACD_TRIGGER_COLOR,
        size: compact ? 0.7 : 1,
      });
    }
    createSeriesMarkers(series, markers);

    const visible = Math.min(candles.length, visibleBars);
    chart.timeScale().setVisibleLogicalRange({ from: candles.length - visible - 0.5, to: candles.length + (compact ? 1 : 4) });

    return () => {
      cancelAnimationFrame(fitFrame);
      chart.remove();
    };
  }, [candles, height, visibleBars, compact, lines, macdPane]);

  return (
    <div className="chart-block">
      {(lines.length > 0 || macdPane) && (
        <div className="ma-legend">
          {lines.length > 0 && (
            <span className="ma-group" title={MA_LEGEND_TITLE}>
              {lines.map((average) => (
                <span key={average.period}>
                  <i style={{ background: average.color }} />
                  {average.period}
                </span>
              ))}
            </span>
          )}
          {macdPane && (
            <>
              <span className="macd-label" title={MACD_TOOLTIP}>
                <i style={{ background: MACD_COLORS.histogramUp }} />
                <i style={{ background: MACD_COLORS.histogramDown }} />
                {macdPane.label}
              </span>
              <span className="macd-trigger-note" title={MACD_TRIGGER_NOTE}>
                <i className="trigger-swatch" style={{ borderBottomColor: MACD_TRIGGER_COLOR }} />
                {MACD_TRIGGER_NOTE}
              </span>
            </>
          )}
        </div>
      )}
      <div ref={ref} className="chart" style={{ height }} />
    </div>
  );
}
