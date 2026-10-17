import { useCallback, useEffect, useRef, useState } from "react";
import { Navigate, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { LAST_TAB_KEY, pageTitle, readPersisted, restoreTarget, tabLocation, writePersisted } from "./persist";
import { api, type Status } from "./api";
import Scanner from "./pages/Scanner";
import Detail from "./pages/Detail";
import Themes from "./pages/Themes";
import Market from "./pages/Market";
import Watchlist from "./pages/Watchlist";
import Positions from "./pages/Positions";
import { WatchlistProvider, useWatchlist } from "./components/Watch";
import { PositionsProvider, usePositions } from "./components/Positions";
import { LoadingIndicator, RefreshBanner } from "./components/Loading";
import { refreshProgress } from "./loading";

function useStickyTab() {
  const location = useLocation();
  const navigate = useNavigate();
  const restored = useRef(false);

  useEffect(() => {
    if (!restored.current) {
      restored.current = true;
      const target = restoreTarget(location.pathname, location.search, readPersisted<string | null>(LAST_TAB_KEY, null));
      if (target) {
        navigate(target, { replace: true });
        return;
      }
    }
    const tab = tabLocation(location.pathname, location.search);
    if (tab) writePersisted(LAST_TAB_KEY, tab);
    document.title = pageTitle(location.pathname);
  }, [location.pathname, location.search, navigate]);
}

function WatchlistTab() {
  const { symbols } = useWatchlist();
  return (
    <NavLink to="/watchlist">
      Watchlist
      <span className={`count-badge ${symbols.length ? "" : "zero"}`} aria-label={`${symbols.length} watched`}>
        {symbols.length}
      </span>
    </NavLink>
  );
}

function PositionsTab() {
  const { symbols } = usePositions();
  return (
    <NavLink to="/positions">
      Positions
      <span className={`count-badge ${symbols.length ? "" : "zero"}`} aria-label={`${symbols.length} open`}>
        {symbols.length}
      </span>
    </NavLink>
  );
}

export default function App() {
  useStickyTab();
  const [status, setStatus] = useState<Status | null>(null);
  const [connected, setConnected] = useState<boolean | null>(null);
  const [dataVersion, setDataVersion] = useState<string | null>(null);

  const poll = useCallback(async () => {
    try {
      const s = await api.status();
      setStatus(s);
      setConnected(true);
      if (!s.refreshing) setDataVersion(s.last_refresh);
    } catch {
      setStatus(null);
      setConnected(false);
    }
  }, []);

  useEffect(() => {
    poll();
    const id = setInterval(poll, status?.refreshing ? 1500 : 15000);
    return () => clearInterval(id);
  }, [poll, status?.refreshing]);

  const refresh = async () => {
    await api.refresh(false);
    poll();
  };


  return (
    <WatchlistProvider version={dataVersion}>
      <PositionsProvider version={dataVersion}>
        <div className="app">
          <div className="topbar-wrap">
            <header className="topbar">
              <div className="brand">
                <img className="brand-logo" src="/apple-touch-icon.png" alt="" width={30} height={30} />
                <span>
                  Tilt<span className="brand-dim">Killer</span>
                </span>
              </div>
              <nav>
                <NavLink to="/market">State of the Market</NavLink>
                <NavLink to="/themes">Themes</NavLink>
                <NavLink to="/" end>
                  Stock Scanner
                </NavLink>
                <WatchlistTab />
                <PositionsTab />
              </nav>
              <div className="status">
                {status === null ? (
                  connected === null ? <LoadingIndicator label="Connecting…" /> : <span className="muted">API offline</span>
                ) : status.refreshing ? (
                  <LoadingIndicator label={`Refreshing ${refreshProgress(status.progress).pct ?? 0}%`} />
                ) : (
                  <span className="muted">
                    {status.symbols_cached}/{status.universe_size} symbols ·{" "}
                    {status.as_of
                      ? `cut-off view, data through ${status.as_of}`
                      : `updated ${status.last_refresh ? new Date(status.last_refresh).toLocaleString() : "never"}`}
                  </span>
                )}
                <button className="btn" onClick={refresh} disabled={!status || status.refreshing}>
                  ↻ Refresh data
                </button>
              </div>
            </header>
            <RefreshBanner status={status} />
          </div>
          {status?.error && <div className="banner error">Last refresh failed: {status.error}</div>}
          <main>
            <Routes>
              <Route path="/" element={<Scanner version={dataVersion} />} />
              <Route path="/stock/:symbol" element={<Detail version={dataVersion} />} />
              <Route path="/market" element={<Market version={dataVersion} />} />
              <Route path="/themes" element={<Themes version={dataVersion} />} />
              <Route path="/sectors" element={<Navigate to="/themes" replace />} />
              <Route path="/watchlist" element={<Watchlist />} />
              <Route path="/positions" element={<Positions />} />
            </Routes>
          </main>
          <footer className="footer">
            Leadership-first, long-bias · Strat setups as timing · data from Yahoo Finance via yfinance, cached locally · not investment advice
          </footer>
        </div>
      </PositionsProvider>
    </WatchlistProvider>
  );
}
