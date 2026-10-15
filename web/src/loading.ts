export interface RefreshProgress {
  /** Headline, e.g. "Refreshing data… 120/546". */
  label: string;
  /** The backend's current step (e.g. "Downloading AAPL"), when it adds something to the label. */
  detail: string | null;
  /** 0–100, or null while the total is not known yet (indeterminate bar). */
  pct: number | null;
}

export function refreshProgress(progress: { done: number; total: number; message: string }): RefreshProgress {
  const { done, total, message } = progress;
  const earnings = message.startsWith("Earnings dates");
  const detail = message && message !== "Starting" && !earnings ? message : null;
  if (total <= 0) return { label: "Refreshing data… starting", detail, pct: null };
  const clamped = Math.min(Math.max(done, 0), total);
  return {
    label: `${earnings ? "Refreshing earnings dates…" : "Refreshing data…"} ${clamped}/${total}`,
    detail,
    pct: Math.round((clamped / total) * 100),
  };
}
