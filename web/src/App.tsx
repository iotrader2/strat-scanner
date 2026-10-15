import { useCallback, useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { api, type Status } from "./api";
import Scanner from "./pages/Scanner";
import Detail from "./pages/Detail";
import Sectors from "./pages/Sectors";

export default function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [dataVersion, setDataVersion] = useState<string | null>(null);

  const poll = useCallback(async () => {
    try {
      const s = await api.status();
      setStatus(s);
      if (!s.refreshing) setDataVersion(s.last_refresh);
    } catch {
      setStatus(null);
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

  const pct = status && status.progress.total ? Math.round((status.progress.done / status.progress.total) * 100) : 0;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">◆</span>
          <span>
            Strat<span className="brand-dim">Scanner</span>
          </span>
          <span className="local-chip">localhost</span>
        </div>
        <nav>
          <NavLink to="/" end>
            Scanner
          </NavLink>
          <NavLink to="/sectors">Sectors</NavLink>
        </nav>
        <div className="status">
          {status === null ? (
            <span className="muted">API offline</span>
          ) : status.refreshing ? (
            <span className="refreshing">
              <span className="spinner" /> Refreshing {pct}% · {status.progress.message}
            </span>
          ) : (
            <span className="muted">
              {status.symbols_cached}/{status.universe_size} symbols · updated{" "}
              {status.last_refresh ? new Date(status.last_refresh).toLocaleString() : "never"}
            </span>
          )}
          <button className="btn" onClick={refresh} disabled={!status || status.refreshing}>
            ↻ Refresh data
          </button>
        </div>
      </header>
      {status?.error && <div className="banner error">Last refresh failed: {status.error}</div>}
      <main>
        <Routes>
          <Route path="/" element={<Scanner version={dataVersion} />} />
          <Route path="/stock/:symbol" element={<Detail version={dataVersion} />} />
          <Route path="/sectors" element={<Sectors version={dataVersion} />} />
        </Routes>
      </main>
      <footer className="footer">
        Long-bias Strat setups only · data from Yahoo Finance via yfinance, cached locally · not investment advice
      </footer>
    </div>
  );
}
