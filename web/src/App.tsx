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
import { liveStatus, type SocketPhase } from "./live";

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
  const [socket, setSocket] = useState<SocketPhase>("connecting");
  const [dataVersion, setDataVersion] = useState<string | null>(null);
  const [positionsEpoch, setPositionsEpoch] = useState(0);

  const poll = useCallback(async () => {
    try {
      const s = await api.status();
      setStatus(s);
      if (s.version != null) setDataVersion(String(s.version));
    } catch {
      setStatus(null);
    }
  }, []);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let stopped = false;
    let retryMs = 1000;
    let timer = 0;

    const connect = () => {
      if (stopped) return;
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${window.location.host}/ws`);
      ws.onopen = () => setSocket("open");
      ws.onmessage = (ev) => {
        let msg: { type?: string; version?: number; status?: Status };
        try {
          msg = JSON.parse(ev.data);
        } catch {
          return;
        }
        if (msg.type === "ping") return;
        if (msg.type === "positions") setPositionsEpoch((n) => n + 1);
        if (msg.status) setStatus(msg.status);
        if ((msg.type === "snapshot" || msg.type === "delta") && msg.version != null) {
          setDataVersion(String(msg.version));
        }
      };
      ws.onclose = () => {
        if (stopped) return;
        setSocket("reconnecting");
        timer = window.setTimeout(connect, retryMs);
        retryMs = Math.min(retryMs * 2, 15000);
      };
    };

    connect();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      ws?.close();
    };
  }, []);

  useEffect(() => {
    if (socket === "open") return;
    poll();
    const id = window.setInterval(poll, status?.updating || status?.refreshing ? 1500 : 15000);
    return () => window.clearInterval(id);
  }, [poll, socket, status?.updating, status?.refreshing]);

  const live = liveStatus(status, socket);

  return (
    <WatchlistProvider version={dataVersion}>
      <PositionsProvider version={dataVersion} epoch={positionsEpoch}>
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
              <div className="status" role="status" aria-live="polite">
                <span className={`live-dot ${live.tone}`} aria-hidden="true" />
                <span className={live.tone === "busy" ? "refreshing" : "muted"}>{live.label}</span>
              </div>
            </header>
          </div>
          {status?.error && <div className="banner error">Price update failed: {status.error}</div>}
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
            Leadership-first, long-bias · Strat setups as timing · {status?.source === "alpaca"
              ? "prices from Alpaca (IEX live, SIP history), earnings and sectors from Yahoo Finance"
              : "data from Yahoo Finance via yfinance"}, cached locally · logos by{" "}
            <a href="https://parqet.com" target="_blank" rel="noopener noreferrer">Parqet</a> · not investment advice
          </footer>
        </div>
      </PositionsProvider>
    </WatchlistProvider>
  );
}
