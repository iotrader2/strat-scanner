import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, type AlertsPayload, type TradeAlert } from "../api";
import { freshAlerts, notificationText, playChime, triggeredAlerts } from "../alerts";
import { usePersisted } from "../persist";

/** Fallback poll when the socket push is missed; the server pushes right after each poll. */
export const ALERTS_POLL_MS = 60_000;
const FLASH_MS = 12_000;

interface AlertsState {
  today: AlertsPayload | null;
  error: string | null;
  unread: number;
  /** Ids that arrived while this page was open and are still flashing. */
  flashing: Set<number>;
  soundReady: boolean;
  muted: boolean;
  setMuted: (m: boolean) => void;
  enableSound: () => void;
  notifyPermission: NotificationPermission | "unsupported";
  enableNotifications: () => void;
  acknowledge: (ids?: number[]) => Promise<void>;
  reload: () => void;
}

const Ctx = createContext<AlertsState | null>(null);

function notificationSupport(): NotificationPermission | "unsupported" {
  return typeof window !== "undefined" && "Notification" in window ? Notification.permission : "unsupported";
}

/**
 * App-wide alert watcher, so a new alert chimes and notifies on any tab: fetches today's alerts when the server
 * pushes an "alerts" message (epoch) and once a minute, and plays the chime / shows a notification for new ones:
 * once when a stock touches a rising EMA (watch) and again when it trades over the previous candle's high (trigger).
 */
export function AlertsProvider({ epoch, children }: { epoch: number; children: ReactNode }) {
  const [today, setToday] = useState<AlertsPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [flashing, setFlashing] = useState<Set<number>>(new Set());
  const [muted, setMuted] = usePersisted<boolean>("alertsMuted", false);
  const [soundReady, setSoundReady] = useState(false);
  const [notifyPermission, setNotifyPermission] = useState(notificationSupport);
  const audio = useRef<AudioContext | null>(null);
  const seen = useRef<Set<number> | null>(null);
  /** Status of each alert in the previous fetch, so a watch that triggers chimes a second time. */
  const statuses = useRef<Map<number, string> | null>(null);
  const request = useRef(0);
  const mutedRef = useRef(muted);
  mutedRef.current = muted;

  const announce = useCallback((fresh: TradeAlert[], payload: AlertsPayload) => {
    if (!fresh.length) return;
    const ids = fresh.map((a) => a.id);
    setFlashing((prev) => new Set([...prev, ...ids]));
    window.setTimeout(() => {
      setFlashing((prev) => {
        const next = new Set(prev);
        ids.forEach((id) => next.delete(id));
        return next;
      });
    }, FLASH_MS);
    if (!mutedRef.current && audio.current && audio.current.state === "running") playChime(audio.current);
    if (typeof document !== "undefined" && document.hidden && notificationSupport() === "granted") {
      for (const a of fresh) {
        const { title, body } = notificationText(a, payload.setups?.[a.setup] ?? "");
        try {
          const n = new Notification(title, { body, tag: `alert-${a.id}-${a.filled ? "trigger" : "watch"}`, icon: "/apple-touch-icon.png" });
          n.onclick = () => {
            window.focus();
            n.close();
          };
        } catch {
          // Some browsers only allow notifications from a service worker; the chime and flash still happen.
        }
      }
    }
  }, []);

  const reload = useCallback(() => {
    // A lists-poll refetch and an alerts push can be in flight together. Only the latest response is applied,
    // so an older payload cannot wipe a newer alert or a newer EMA reading.
    const id = ++request.current;
    api
      .alerts()
      .then((payload) => {
        if (id !== request.current) return;
        const fresh = [...freshAlerts(payload.alerts, seen.current), ...triggeredAlerts(payload.alerts, statuses.current)];
        seen.current = new Set([...(seen.current ?? []), ...payload.alerts.map((a) => a.id)]);
        statuses.current = new Map([...(statuses.current ?? []), ...payload.alerts.map((a) => [a.id, a.status] as [number, string])]);
        setToday(payload);
        setError(null);
        announce(fresh, payload);
      })
      .catch((e) => {
        if (id !== request.current) return;
        setError(String(e));
      });
  }, [announce]);

  useEffect(reload, [reload, epoch]);
  useEffect(() => {
    const id = window.setInterval(reload, ALERTS_POLL_MS);
    return () => window.clearInterval(id);
  }, [reload]);

  const enableSound = useCallback(() => {
    // Must run inside the click: browsers only start audio from a user gesture.
    const AC = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AC) return;
    if (!audio.current) audio.current = new AC();
    const ctx = audio.current;
    ctx.resume().then(() => {
      setSoundReady(ctx.state === "running");
      if (ctx.state === "running") playChime(ctx);
    });
    if (muted) setMuted(false);
  }, [muted, setMuted]);

  const enableNotifications = useCallback(() => {
    if (notificationSupport() === "unsupported") return;
    Notification.requestPermission().then((p) => setNotifyPermission(p));
  }, []);

  const acknowledge = useCallback(
    async (ids?: number[]) => {
      await api.ackAlerts(ids);
      reload();
    },
    [reload],
  );

  const value = useMemo<AlertsState>(
    () => ({
      today,
      error,
      unread: today?.unread ?? 0,
      flashing,
      soundReady,
      muted,
      setMuted,
      enableSound,
      notifyPermission,
      enableNotifications,
      acknowledge,
      reload,
    }),
    [today, error, flashing, soundReady, muted, setMuted, enableSound, notifyPermission, enableNotifications, acknowledge, reload],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAlerts(): AlertsState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAlerts must be used inside AlertsProvider");
  return ctx;
}
