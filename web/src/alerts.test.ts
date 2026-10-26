import { describe, expect, it } from "vitest";
import type { TradeAlert } from "./api";
import { alertDayStatus, fmtR, freshAlerts, notificationText, phoenixTime, playChime, riskPerShare, statusTone, stopPct, todayEmptyLead } from "./alerts";

export const sample = (over: Partial<TradeAlert> = {}): TradeAlert => ({
  id: 1,
  symbol: "AAPL",
  session: "2026-10-23",
  setup: "A",
  setup_bar: "2026-10-23T13:30:00Z",
  fired_at: "2026-10-23T13:35:00Z",
  detected_at: "2026-10-23T13:36:00Z",
  late: false,
  top: true,
  trigger_price: 101.01,
  stop_price: 99.89,
  setup_low: 99.9,
  setup_high: 101,
  ref_price: 100.9,
  status: "pending",
  filled: false,
  fill_price: null,
  fill_at: null,
  high_reached: null,
  stop_hit: false,
  breakeven_at: null,
  exit_price: null,
  exit_at: null,
  exit_reason: null,
  r_multiple: null,
  details: {},
  acknowledged: false,
  ...over,
});

describe("alert windows", () => {
  const at = (iso: string, settings?: Record<string, number>) => alertDayStatus(new Date(iso), settings);
  const chip = (iso: string, setup: string) => at(iso).windows.find((w) => w.setup === setup)!;

  it("uses Phoenix clock times, and shifts them when New York leaves daylight time", () => {
    const summer = at("2026-10-23T13:00:00Z");
    expect(summer.phase).toBe("before");
    expect(summer.headline).toBe("Alerts start at 6:35 AM Phoenix.");
    expect(summer.detail).toBe("Window 6:35 AM – 1:00 PM Phoenix.");
    expect(chip("2026-10-23T13:00:00Z", "A").label).toBe("6:35 AM");
    expect(chip("2026-10-23T13:00:00Z", "B").label).toBe("6:40–7:00 AM");
    expect(chip("2026-10-23T13:00:00Z", "C").label).toBe("6:40–7:00 AM");
    expect(chip("2026-10-23T13:00:00Z", "D").label).toBe("7:00–7:35 AM");
    expect(chip("2026-10-23T13:00:00Z", "E").label).toBe("6:45–7:55 AM");
    expect(chip("2026-10-23T13:00:00Z", "F").label).toBe("8:35 AM – 1:00 PM");

    const winter = at("2026-11-02T14:00:00Z");
    expect(winter.phase).toBe("before");
    expect(winter.headline).toBe("Alerts start at 7:35 AM Phoenix.");
    expect(winter.detail).toBe("Window 7:35 AM – 2:00 PM Phoenix.");
    expect(winter.windows.find((w) => w.setup === "F")?.label).toBe("9:35 AM – 2:00 PM");
  });

  it("says which setups can still fire, including the gap before the midday window", () => {
    const mid = at("2026-10-23T13:50:00Z");
    expect(mid.phase).toBe("open");
    expect(mid.headline).toBe("Alerts can still fire until 1:00 PM Phoenix.");
    expect(chip("2026-10-23T13:50:00Z", "A").state).toBe("done");
    expect(chip("2026-10-23T13:50:00Z", "B").state).toBe("open");
    expect(chip("2026-10-23T13:50:00Z", "E").state).toBe("open");
    expect(chip("2026-10-23T13:50:00Z", "F").state).toBe("later");

    const gap = at("2026-10-23T15:10:00Z");
    expect(gap.phase).toBe("open");
    expect(gap.headline).toBe("F can fire 8:35 AM – 1:00 PM Phoenix.");
    expect(gap.detail).toBe("Alerts finish at 1:00 PM Phoenix.");
    expect(gap.windows.filter((w) => w.setup !== "F").every((w) => w.state === "done")).toBe(true);
    expect(gap.windows.find((w) => w.setup === "F")?.state).toBe("later");
  });

  it("says alerts are done for the day after the last window", () => {
    const done = at("2026-10-23T20:01:00Z");
    expect(done.phase).toBe("done");
    expect(done.headline).toBe("Alerts are done for the day.");
    expect(done.detail).toBe("The window was 6:35 AM – 1:00 PM Phoenix.");
    expect(done.windows.every((w) => w.state === "done")).toBe(true);
    expect(todayEmptyLead(done)).toBe("Alerts are done for the day. The window was 6:35 AM – 1:00 PM Phoenix.");
    expect(todayEmptyLead(at("2026-10-23T15:10:00Z"))).toBeNull();
  });

  it("names the next session on a weekend", () => {
    const sat = at("2026-10-24T15:00:00Z");
    expect(sat.phase).toBe("closed");
    expect(sat.headline).toBe("Market is closed.");
    expect(sat.detail).toBe("Next window is Monday, 6:35 AM – 1:00 PM Phoenix.");
    expect(sat.windows.every((w) => w.state === "later")).toBe(true);
  });

  it("follows a saved window instead of the default", () => {
    const day = at("2026-10-23T13:00:00Z", { e_from: 10, e_to: 200 });
    expect(day.windows.find((w) => w.setup === "E")?.label).toBe("6:45–9:55 AM");
  });
});

describe("alerts helpers", () => {
  it("shows Phoenix time all year (no daylight saving)", () => {
    expect(phoenixTime("2026-10-23T13:35:00Z")).toBe("6:35 AM");
    expect(phoenixTime("2026-11-02T14:35:00Z")).toBe("7:35 AM");
    expect(phoenixTime(null)).toBe("—");
  });

  it("risk per share and stop percent come from trigger and stop", () => {
    expect(riskPerShare(sample())).toBeCloseTo(1.12);
    expect(stopPct(sample())).toBeCloseTo((1.12 / 101.01) * 100);
  });

  it("formats R with a sign", () => {
    expect(fmtR(1.234)).toBe("+1.23R");
    expect(fmtR(-1)).toBe("-1.00R");
    expect(fmtR(null)).toBe("—");
    expect(fmtR(0.0003)).toBe("0.00R");
    expect(fmtR(-0.001)).toBe("0.00R");
  });

  it("status tone", () => {
    expect(statusTone(sample())).toBe("wait");
    expect(statusTone(sample({ status: "triggered" }))).toBe("live");
    expect(statusTone(sample({ status: "exited", r_multiple: 1.5 }))).toBe("good");
    expect(statusTone(sample({ status: "stopped", r_multiple: -1 }))).toBe("bad");
    expect(statusTone(sample({ status: "breakeven", r_multiple: 0 }))).toBe("flat");
  });

  it("chimes only for alerts new since the last fetch, never on the first load or for late ones", () => {
    const a = sample({ id: 1 });
    const b = sample({ id: 2 });
    const late = sample({ id: 3, late: true });
    const read = sample({ id: 4, acknowledged: true });
    expect(freshAlerts([a, b], null)).toEqual([]);
    expect(freshAlerts([a, b, late, read], new Set([1]))).toEqual([b]);
  });

  it("plays three separate beeps", () => {
    const starts: number[] = [];
    const stops: number[] = [];
    const ctx = {
      currentTime: 10,
      destination: {},
      createGain: () => ({
        gain: { setValueAtTime() {}, exponentialRampToValueAtTime() {} },
        connect() {
          return this;
        },
      }),
      createOscillator: () => ({
        frequency: { value: 0 },
        connect() {
          return this;
        },
        start(t: number) {
          starts.push(t);
        },
        stop(t: number) {
          stops.push(t);
        },
      }),
    } as unknown as AudioContext;
    playChime(ctx);
    expect(starts).toEqual([10, 10.28, 10.56]);
    expect(stops[0]).toBeLessThanOrEqual(starts[1]);
    expect(stops[1]).toBeLessThanOrEqual(starts[2]);
  });

  it("notification text has the levels and no emoji", () => {
    const { title, body } = notificationText(sample(), "Opening-bar breakout");
    expect(title).toBe("AAPL setup A (top)");
    expect(body).toContain("Buy stop 101.01, stop 99.89");
    expect(body).toContain("6:35 AM Phoenix");
    expect(/\p{Extended_Pictographic}/u.test(title + body)).toBe(false);
  });
});
