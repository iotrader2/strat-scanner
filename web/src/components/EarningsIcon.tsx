import type { Earnings } from "../api";
import { earningsLines } from "../earnings";

/** ⚠ shown when the stock reports within the next 10 calendar days. */
export function EarningsIcon({ earnings }: { earnings: Earnings | null | undefined }) {
  if (!earnings) return null;
  const lines = earningsLines(earnings);

  return (
    <span className="earnings-icon" role="img" aria-label={lines.join(", ")} onClick={(e) => e.stopPropagation()}>
      ⚠
    </span>
  );
}
