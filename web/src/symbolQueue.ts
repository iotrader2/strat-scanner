import { useCallback, useLayoutEffect, useRef, useState } from "react";

/** Outcome of the symbols submitted since the queue was last idle. */
export interface QueueResult {
  ok: string[];
  failed: { symbol: string; error: string }[];
}

interface Item<T> {
  symbol: string;
  payload: T;
}

/**
 * Add-ticker queue for the Watchlist and Positions add boxes. Each Enter enqueues one symbol and returns at once, so the
 * input is cleared and keeps focus (and the iPad keyboard stays up) while earlier adds are still in flight. Requests run
 * one at a time in submit order: each response replaces the whole list, so overlapping requests could otherwise land
 * out of order. A symbol already waiting is not queued twice.
 */
export function useSymbolQueue<T>(run: (symbol: string, payload: T) => Promise<void>) {
  const runRef = useRef(run);
  useLayoutEffect(() => {
    runRef.current = run;
  });
  const queue = useRef<Item<T>[]>([]);
  const running = useRef(false);
  const batch = useRef<QueueResult>({ ok: [], failed: [] });
  const [pending, setPending] = useState<string[]>([]);
  const [result, setResult] = useState<QueueResult | null>(null);

  const drain = useCallback(async () => {
    if (running.current) return;
    running.current = true;
    try {
      while (queue.current.length > 0) {
        const item = queue.current[0];
        try {
          await runRef.current(item.symbol, item.payload);
          batch.current.ok.push(item.symbol);
        } catch (err) {
          batch.current.failed.push({ symbol: item.symbol, error: err instanceof Error ? err.message : String(err) });
        }
        queue.current.shift();
        setPending(queue.current.map((q) => q.symbol));
        setResult({ ok: [...batch.current.ok], failed: [...batch.current.failed] });
      }
    } finally {
      running.current = false;
    }
  }, []);

  const isPending = useCallback((symbol: string) => queue.current.some((q) => q.symbol === symbol), []);

  /** Queue one symbol. Returns false when it is already waiting. */
  const enqueue = useCallback(
    (symbol: string, payload: T) => {
      if (isPending(symbol)) return false;
      if (!running.current) {
        batch.current = { ok: [], failed: [] };
        setResult(null);
      }
      queue.current.push({ symbol, payload });
      setPending(queue.current.map((q) => q.symbol));
      void drain();
      return true;
    },
    [drain, isPending],
  );

  return { enqueue, pending, result, isPending };
}

/** "Added SPY, QQQ" style summary of a batch, with failures listed separately. */
export function queueSummary(result: QueueResult | null, verb: string): { ok: string | null; error: string | null } {
  if (!result) return { ok: null, error: null };
  return {
    ok: result.ok.length > 0 ? `${verb} ${result.ok.join(", ")}` : null,
    error: result.failed.length > 0 ? result.failed.map((f) => `${f.symbol}: ${f.error}`).join(" · ") : null,
  };
}
