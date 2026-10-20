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
  trim: (symbol: string, req: { shares: number; price: number }) => Promise<void>;
  undoTrim: (symbol: string, trimId: number) => Promise<void>;
}

const PositionsContext = createContext<PositionsState | null>(null);

/** Must sit inside WatchlistProvider: moves between the two lists refresh both. */
export function PositionsProvider({
  version,
  epoch = 0,
  children,
}: {
  version: string | null;
  /** Bumps when another client trims, so this tab refetches without a refresh button. */
  epoch?: number;
  children: ReactNode;
}) {
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
  }, [apply, version, epoch]);

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
  const trim = useCallback(
    async (symbol: string, req: { shares: number; price: number }) => apply(await api.trimPosition(symbol, req)),
    [apply],
  );
  const undoTrim = useCallback(
    async (symbol: string, trimId: number) => apply(await api.undoTrim(symbol, trimId)),
    [apply],
  );

  const symbols = useMemo(() => data?.symbols ?? [], [data]);
  const value = useMemo<PositionsState>(
    () => ({ symbols, data, error, isHeld: (s) => symbols.includes(s), open, update, close, toWatchlist, trim, undoTrim }),
    [symbols, data, error, open, update, close, toWatchlist, trim, undoTrim],
  );
  return <PositionsContext.Provider value={value}>{children}</PositionsContext.Provider>;
}

export function usePositions(): PositionsState {
  const ctx = useContext(PositionsContext);
  if (!ctx) throw new Error("usePositions must be used inside PositionsProvider");
  return ctx;
}
