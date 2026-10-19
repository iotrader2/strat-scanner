import type { Status } from "./api";

export type LiveTone = "live" | "busy" | "stale" | "off";
export type SocketPhase = "connecting" | "open" | "reconnecting";

export interface LiveView {
  tone: LiveTone;
  label: string;
}

/** Clock time in the browser's timezone, without a date. "12:45 PM PDT". */
export function formatLocal(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "never";
  return new Intl.DateTimeFormat("en-US", {
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(d);
}

export function liveStatus(status: Status | null, socket: SocketPhase): LiveView {
  if (socket === "connecting") return { tone: "off", label: "Connecting" };
  if (socket !== "open" || status === null) return { tone: "off", label: "Reconnecting" };
  if (status.as_of) return { tone: "stale", label: `Cut-off view, data through ${status.as_of}` };
  if (status.updating || status.refreshing) {
    const total = status.progress?.total ?? 0;
    const done = status.progress?.done ?? 0;
    const n = total > 0 ? `${Math.min(Math.max(done, 0), total)}/${total}` : null;
    return { tone: "busy", label: n ? `Updating · ${n} symbols` : "Updating" };
  }
  const when = status.computed_at || status.last_refresh;
  return { tone: "live", label: `15-min delayed · updated ${when ? formatLocal(when) : "never"}` };
}
