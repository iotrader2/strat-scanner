import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { api, type AppConfig } from "../api";
import { filterForKind, paramLabel, paramValue, ruleSteps, type SetupDoc } from "../setupDocs";

const FILE = "backend/data/setups.yaml";

/** One setup as the code runs it: rules with the numbers filled in, entry, stop, and every number. */
function SetupCard({ doc }: { doc: SetupDoc }) {
  const steps = ruleSteps(doc.rules, doc.params);
  // Rules that start with a lead-in line ("Same-day trade on TODAY's bar:") show it above the numbered steps.
  const intro = /^\s*1\.\s/.test(doc.rules) ? null : steps.shift() ?? null;
  const longFilter = filterForKind(doc.kind);
  const shortFilter = filterForKind(doc.short_kind);
  return (
    <section className="card setup-doc" id={doc.kind}>
      <header className="setup-doc-head">
        <div>
          <h2>{doc.name}</h2>
          <div className="muted small">
            Short mirror: <span id={doc.short_kind}>{doc.short_name}</span>
          </div>
        </div>
        <div className="setup-doc-links">
          {longFilter && (
            <Link className="btn small" to={`/?setup=${longFilter}`}>
              Scan long
            </Link>
          )}
          {shortFilter && (
            <Link className="btn small" to={`/?setup=${shortFilter}`}>
              Scan short
            </Link>
          )}
        </div>
      </header>
      <div className="setup-doc-body">
        <div>
          <div className="field-label">Rules</div>
          {intro && <p className="setup-doc-intro">{intro}</p>}
          <ol className="setup-doc-steps">
            {steps.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ol>
          <div className="field-label">Entry</div>
          <p>{ruleSteps(doc.entry, doc.params).join(" ")}</p>
          <div className="field-label">Stop</div>
          <p>{ruleSteps(doc.stop, doc.params).join(" ")}</p>
        </div>
        <div>
          <div className="field-label">Numbers</div>
          <table className="setup-doc-params">
            <tbody>
              {Object.entries(doc.params).map(([k, v]) => (
                <tr key={k}>
                  <td>
                    {paramLabel(k)}
                    <div className="muted mono">{k}</div>
                  </td>
                  <td className="num">{paramValue(k, v)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

export default function Setups() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { hash } = useLocation();
  const docs = config?.setups ?? [];
  const overview = config?.setups_overview;

  useEffect(() => {
    api.config().then(setConfig).catch((e) => setError(String(e)));
  }, []);

  // Jump to #kind once the cards exist (links from the scanner and the detail page).
  useEffect(() => {
    if (!hash || !docs.length) return;
    document.getElementById(decodeURIComponent(hash.slice(1)))?.closest(".setup-doc")?.scrollIntoView({ block: "start" });
  }, [hash, docs.length]);

  return (
    <div className="page setups-page">
      <section className="hero">
        <div>
          <h1>Setups</h1>
          <p className="muted">
            Each daily setup exactly as the scanner runs it. The numbers come from <code>{FILE}</code>; change one there
            and the scanner changes with it. To change a rule, say what it should be and the code and file change together.
          </p>
        </div>
      </section>

      {error && <div className="banner error">{error}</div>}

      {docs.length > 0 && (
        <nav className="setup-jump" aria-label="Jump to a setup">
          {docs.map((d) => (
            <a key={d.kind} href={`#${d.kind}`} onClick={(e) => {
              e.preventDefault();
              document.getElementById(d.kind)?.scrollIntoView({ block: "start", behavior: "smooth" });
              history.replaceState(null, "", `#${d.kind}`);
            }}>
              {d.name}
            </a>
          ))}
        </nav>
      )}

      {overview && (
        <section className="card setup-doc">
          <h2>How every setup works</h2>
          <ul className="setup-doc-steps">
            {overview.how_it_works.map((t, i) => (
              <li key={i}>{t}</li>
            ))}
          </ul>
          <div className="field-label">Short setups</div>
          <p>{overview.short_setups}</p>
          <div className="field-label">Playbook rules (shown, not enforced)</div>
          <p className="muted">
            Entry chart {String(overview.general.entry_chart_minutes)} min · risk {String(overview.general.risk_pct_min)}–
            {String(overview.general.risk_pct_max)}% of equity per trade · partials after{" "}
            {Array.isArray(overview.general.partial_profit_after_days) ? overview.general.partial_profit_after_days.join("–") : ""} strong days ·
            trail with the {Array.isArray(overview.general.trail_ma_periods) ? overview.general.trail_ma_periods.join("/") : ""}-day average ·
            at least {String(overview.general.min_history_days)} days of history
          </p>
        </section>
      )}

      {config === null && !error ? (
        <div className="card empty-state">Loading setups…</div>
      ) : (
        docs.map((d) => <SetupCard key={d.kind} doc={d} />)
      )}
    </div>
  );
}
