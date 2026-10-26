import { useMemo, type ComponentProps } from "react";
import type { ListIntraday } from "../api";
import { crossHighlight } from "../listIntraday";
import { listIntradayColumns } from "./ListIntradayColumns";
import { ScanTable, type ExtraColumn } from "./ScanTable";

type ScanTableProps = ComponentProps<typeof ScanTable>;

/**
 * The one table layout shared by Watchlist and Positions, so a column added or removed here applies to both:
 * the trading-list column set (no 1M / 3M / 6M, no D · W · M, no Weekly setup), Score immediately right of Price,
 * the premarket and 5-minute EMA columns, and the 5-minute EMA crossover row highlight. Positions passes its own
 * position columns (entry, P/L, days held) ahead of the shared intraday ones.
 */
export function ListTable({
  intraday,
  extraColumns = [],
  ...props
}: Omit<ScanTableProps, "tradingList" | "rowHighlight"> & {
  intraday: Record<string, ListIntraday> | undefined;
  extraColumns?: ExtraColumn[];
}) {
  const columns = useMemo(() => [...extraColumns, ...listIntradayColumns(intraday)], [extraColumns, intraday]);
  return (
    <ScanTable
      {...props}
      tradingList
      extraColumns={columns}
      rowHighlight={(r) => crossHighlight(intraday?.[r.symbol])}
    />
  );
}
