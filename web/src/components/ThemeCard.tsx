import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { fmtPct, type ThemeCard as ThemeCardData, type ThemeChip } from "../api";
import { fmtPerf } from "../perf";
import { scanThemeHref } from "../themes";
import { ScorePill, TfBadges } from "./Badges";
import { CandleChart } from "./CandleChart";
import { PerfStrip } from "./PerfStrip";

const VISIBLE_CHIPS = 12;
/** Recent bars kept in view so each candle is large enough to read on a theme card. */
const VISIBLE_BARS = 18;

function Chip({ chip }: { chip: ThemeChip }) {
  const m1 = chip.perf?.["1m"];
  return (
    <Link
      to={`/stock/${chip.symbol}`}
      className={`member-chip ${chip.mw_green ? "green" : ""} ${chip.also ? "also" : ""} ${chip.has_setup ? "setup" : ""}`}
      title={`${chip.name}${chip.also ? " (secondary member, not in the index)" : ""} · day ${fmtPct(chip.change_pct, 2)} · 1M ${fmtPerf(m1)} · score ${chip.score.toFixed(0)}${chip.has_setup ? " · weekly setup" : ""}`}
    >
      {chip.symbol}
      <span className={`member-day ${chip.change_pct >= 0 ? "green-text" : "red-text"}`}>{fmtPerf(chip.change_pct)}</span>
    </Link>
  );
}

/** Theme card: equal-weight index candles with H/I markers, M/W/D badges, score, returns, members and a Scan theme link. */
export function ThemeCard({ theme, chartHeight = 240 }: { theme: ThemeCardData; chartHeight?: number }) {
  const r = theme.row;
  const [expanded, setExpanded] = useState(false);
  const setup = r.setups?.[0];
  const chips = useMemo(() => [...theme.members, ...theme.also], [theme.members, theme.also]);
  const shown = expanded ? chips : chips.slice(0, VISIBLE_CHIPS);
  const hidden = chips.length - shown.length;

  return (
    <div className={`card sector-card theme-card ${r.mw_green ? "mw-green" : ""}`} data-theme-id={theme.id}>
      <div className="sector-head">
        <div>
          <div className="sym theme-name" title={theme.description}>{theme.name}</div>
          <div className="sub muted theme-sub" title={theme.description}>{theme.description}</div>
        </div>
        <div className="sector-right">
          <span className="num">{r.price.toFixed(1)}</span>
          <span className={`small ${r.change_pct >= 0 ? "green-text" : "red-text"}`}>{fmtPct(r.change_pct, 2)}</span>
        </div>
      </div>
      <div className="sector-badges">
        <TfBadges tf={r.tf} />
        <ScorePill score={r.score} row={r} />
      </div>
      <PerfStrip perf={r.perf} label={`${theme.name} equal-weight index performance`} />
      <CandleChart candles={theme.candles} height={chartHeight} visibleBars={VISIBLE_BARS} compact />
      <div className="sector-foot">
        <span className="small">
          {setup ? (
            <>
              <b>W</b> {setup.label} · trigger <span className="accent-text">{setup.trigger.toFixed(1)}</span>
            </>
          ) : (
            <span className="muted">No weekly setup</span>
          )}
        </span>
        <Link className="chip scan-theme" to={scanThemeHref(theme.id)}>
          Scan theme →
        </Link>
      </div>
      <div className="member-chips" aria-label={`${theme.name} members`}>
        {shown.map((c) => (
          <Chip key={c.symbol} chip={c} />
        ))}
        {(hidden > 0 || expanded) && chips.length > VISIBLE_CHIPS && (
          <button type="button" className="member-more" onClick={() => setExpanded((v) => !v)}>
            {expanded ? "show fewer" : `+${hidden} more`}
          </button>
        )}
      </div>
      <div className="member-note muted small">
        {theme.count} in the equal-weight index
        {theme.also.length > 0 && <> · dimmed = also tied to this theme</>}
      </div>
    </div>
  );
}
