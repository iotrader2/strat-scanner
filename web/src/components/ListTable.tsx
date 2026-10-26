import { useMemo, type ComponentProps } from "react";
import type { ListIntraday } from "../api";
import { crossHighlight } from "../listIntraday";
import { listIntradayColumns } from "./ListIntradayColumns";
import { ScanTable, type ExtraColumn } from "./ScanTable";

type ScanTableProps = ComponentProps<typeof ScanTable>;

/**
 * The table layout shared by Watchlist and Positions: the trading-list column set (no 1M / 3M / 6M, no D · W · M,
 * no Weekly setup), Score immediately right of Price, then premarket, Day, Day range and the daily vs-MA columns.
 *
 * The 5-minute 6/20 EMA pills and the crossover row highlight are the exception. They stay on Positions
 * (`showEma5m`) because those names are watched on the 5-minute chart for end-of-day sells. The watchlist
 * does not show them. Nothing else on the watchlist reads the crossover, so the row highlight goes with the columns.
 * Positions passes its own position columns (entry, P/L, days held) ahead of the shared intraday ones.
 */
export function ListTable({
  intraday,
  extraColumns = [],
  showEma5m = false,
  ...props
}: Omit<ScanTableProps, "tradingList" | "rowHighlight"> & {
  intraday: Record<string, ListIntraday> | undefined;
  extraColumns?: ExtraColumn[];
  /** Positions only. Watchlist leaves this off. */
  showEma5m?: boolean;
}) {
  const columns = useMemo(
    () => [...extraColumns, ...listIntradayColumns(intraday, { ema5m: showEma5m })],
    [extraColumns, intraday, showEma5m],
  );
  return (
    <ScanTable
      {...props}
      tradingList
      extraColumns={columns}
      rowHighlight={showEma5m ? (r) => crossHighlight(intraday?.[r.symbol]) : undefined}
    />
  );
}
