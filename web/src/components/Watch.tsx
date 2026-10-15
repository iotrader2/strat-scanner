import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, type Watchlist } from "../api";
import { withSymbol } from "../watchlist";

interface WatchState {
  symbols: string[];
  data: Watchlist | null;
  error: string | null;
  isWatched: (symbol: string) => boolean;
  toggle: (symbol: string) => void;
  /** Add any ticker; rejects with the server's message (e.g. unknown symbol). */
  add: (symbol: string) => Promise<void>;
  /** Re-fetch after the server changed the list (e.g. a name moved to or from Positions). */
  reload: () => void;
}

const WatchContext = createContext<WatchState | null>(null);

export function WatchlistProvider({ version, children }: { version: string | null; children: ReactNode }) {
  const [data, setData] = useState<Watchlist | null>(null);
  const [symbols, setSymbols] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const apply = useCallback((w: Watchlist) => {
    setData(w);
    setSymbols(w.symbols);
    setError(null);
  }, []);

  const reload = useCallback(() => {
    api.watchlist().then(apply).catch((e) => setError(String(e)));
  }, [apply]);

  useEffect(reload, [reload, version]);

  const toggle = useCallback(
    (symbol: string) => {
      const on = !symbols.includes(symbol);
      setSymbols((s) => withSymbol(s, symbol, on));
      (on ? api.watch(symbol) : api.unwatch(symbol)).then(apply).catch((e) => {
        setError(String(e));
        reload();
      });
    },
    [symbols, apply, reload],
  );

  const add = useCallback(
    async (symbol: string) => {
      apply(await api.watch(symbol));
    },
    [apply],
  );

  const value = useMemo<WatchState>(
    () => ({ symbols, data, error, isWatched: (s) => symbols.includes(s), toggle, add, reload }),
    [symbols, data, error, toggle, add, reload],
  );
  return <WatchContext.Provider value={value}>{children}</WatchContext.Provider>;
}

export function useWatchlist(): WatchState {
  const ctx = useContext(WatchContext);
  if (!ctx) throw new Error("useWatchlist must be used inside WatchlistProvider");
  return ctx;
}

/** "+" adds the symbol; when watched it shows a check that turns into "−" on hover. */
export function WatchButton({ symbol, labelled = false }: { symbol: string; labelled?: boolean }) {
  const { isWatched, toggle } = useWatchlist();
  const on = isWatched(symbol);
  return (
    <button
      type="button"
      className={`watch-btn ${on ? "on" : ""} ${labelled ? "labelled" : ""}`}
      aria-pressed={on}
      aria-label={on ? `Remove ${symbol} from watchlist` : `Add ${symbol} to watchlist`}
      title={on ? "On your watchlist — click to remove" : "Add to watchlist"}
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        toggle(symbol);
      }}
    >
      {on ? (
        <>
          <span className="when-idle">✓{labelled && " Watching"}</span>
          <span className="when-hover">−{labelled && " Remove"}</span>
        </>
      ) : (
        <>+{labelled && " Watchlist"}</>
      )}
    </button>
  );
}
