import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, type PositionInput, type Positions } from "../api";
import { useWatchlist } from "./Watch";

interface PositionsState {
  symbols: string[];
  data: Positions | null;
  error: string | null;
  isHeld: (symbol: string) => boolean;
  /** Open a position (any ticker); the server drops it from the watchlist. Rejects with the server's message. */
  open: (symbol: string, entry: PositionInput) => Promise<void>;
  update: (symbol: string, entry: { entry_price: number; shares: number | null; entry_date: string }) => Promise<void>;
  close: (symbol: string) => Promise<void>;
  toWatchlist: (symbol: string) => Promise<void>;
}

const PositionsContext = createContext<PositionsState | null>(null);

/** Must sit inside WatchlistProvider: moves between the two lists refresh both. */
export function PositionsProvider({ version, children }: { version: string | null; children: ReactNode }) {
  const watch = useWatchlist();
  const reloadWatch = watch.reload;
  const [data, setData] = useState<Positions | null>(null);
  const [error, setError] = useState<string | null>(null);

  const apply = useCallback((p: Positions) => {
    setData(p);
    setError(null);
  }, []);

  useEffect(() => {
    api.positions().then(apply).catch((e) => setError(String(e)));
  }, [apply, version]);

  const open = useCallback(
    async (symbol: string, entry: PositionInput) => {
      apply(await api.openPosition({ symbol, ...entry }));
      reloadWatch();
    },
    [apply, reloadWatch],
  );
  const update = useCallback<PositionsState["update"]>(
    async (symbol, entry) => apply(await api.updatePosition(symbol, entry)),
    [apply],
  );
  const close = useCallback(async (symbol: string) => apply(await api.closePosition(symbol)), [apply]);
  const toWatchlist = useCallback(
    async (symbol: string) => {
      apply(await api.positionToWatchlist(symbol));
      reloadWatch();
    },
    [apply, reloadWatch],
  );

  const symbols = useMemo(() => data?.symbols ?? [], [data]);
  const value = useMemo<PositionsState>(
    () => ({ symbols, data, error, isHeld: (s) => symbols.includes(s), open, update, close, toWatchlist }),
    [symbols, data, error, open, update, close, toWatchlist],
  );
  return <PositionsContext.Provider value={value}>{children}</PositionsContext.Provider>;
}

export function usePositions(): PositionsState {
  const ctx = useContext(PositionsContext);
  if (!ctx) throw new Error("usePositions must be used inside PositionsProvider");
  return ctx;
}
