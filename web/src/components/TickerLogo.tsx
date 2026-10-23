import { useState } from "react";

/** Same-origin logo endpoint (backend/strat/logos.py): disk-cached on the server, cached a week by the browser. */
export function logoUrl(symbol: string): string {
  return `/api/logo/${encodeURIComponent(symbol.toUpperCase())}`;
}

/** First character shown when there is no logo (a letter or digit; "?" for anything else). */
export function logoLetter(symbol: string): string {
  const c = symbol.trim().charAt(0).toUpperCase();
  return /[A-Z0-9]/.test(c) ? c : "?";
}

type ViewProps = { symbol: string; size: number; className?: string; failed: boolean; onFail: () => void };

/** Stateless markup: a fixed box with the letter avatar, plus the lazy image until it fails. */
export function TickerLogoView({ symbol, size, className = "", failed, onFail }: ViewProps) {
  return (
    <span
      className={`ticker-logo ${failed ? "no-logo" : ""} ${className}`}
      style={{ width: size, height: size, fontSize: Math.round(size * 0.5) }}
      aria-hidden="true"
    >
      <span className="ticker-logo-letter">{logoLetter(symbol)}</span>
      {!failed && (
        <img
          src={logoUrl(symbol)}
          alt=""
          width={size}
          height={size}
          loading="lazy"
          decoding="async"
          draggable={false}
          onError={onFail}
          onLoad={(e) => {
            if (!e.currentTarget.naturalWidth) onFail();
          }}
        />
      )}
    </span>
  );
}

/**
 * Small company / fund logo left of a ticker. The box is always `size` x `size` with the letter avatar underneath, and
 * the image (lazy-loaded) covers it once it loads, so a slow, missing or broken logo never moves the layout.
 */
export function TickerLogo({ symbol, size = 20, className = "" }: { symbol: string; size?: number; className?: string }) {
  const [failed, setFailed] = useState(false);
  return <TickerLogoView symbol={symbol} size={size} className={className} failed={failed} onFail={() => setFailed(true)} />;
}
