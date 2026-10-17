import type { Perf } from "../api";
import { fmtPerf, perfClass, PERF_PERIODS } from "../perf";

/** 1M / 3M / 6M price returns, green for gains and red for losses. */
export function PerfStrip({ perf, label }: { perf: Perf | undefined; label?: string }) {
  return (
    <div className="perf-strip" aria-label={label ?? "Price performance"}>
      {PERF_PERIODS.map((p) => (
        <span key={p.key} className="perf-item">
          <span className="perf-label">{p.label}</span>
          <span className={`perf-value ${perfClass(perf?.[p.key])}`}>{fmtPerf(perf?.[p.key])}</span>
        </span>
      ))}
    </div>
  );
}
