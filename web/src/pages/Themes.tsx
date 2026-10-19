import { useEffect, useMemo, useState, type MouseEvent } from "react";
import { api, type ThemeCard as ThemeCardData, type Tf } from "../api";
import { isTimeframe, usePersisted } from "../persist";
import { CARD_BARS, TfToggle } from "../components/EtfCard";
import { LoadingIndicator, SkeletonCards } from "../components/Loading";
import { ThemeCard } from "../components/ThemeCard";
import { filterThemes, sortThemes, THEME_SORTS, type ThemeSort } from "../themeCards";

const PAGE = 24;
const LEADERS = 12;
type RankDir = "top" | "bottom";

export default function Themes({ version }: { version: string | null }) {
  const [storedTf, setTf] = usePersisted<Tf>("themesTf", "W");
  const tf: Tf = isTimeframe(storedTf) ? storedTf : "W";
  const [storedSort, setSort] = usePersisted<ThemeSort>("themesSort", "score");
  const sort: ThemeSort = THEME_SORTS.some((s) => s.key === storedSort) ? storedSort : "score";
  const [storedRank, setRankDir] = usePersisted<RankDir>("themesRank", "top");
  const rankDir: RankDir = storedRank === "bottom" ? "bottom" : "top";
  const [themes, setThemes] = useState<ThemeCardData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [shown, setShown] = useState(PAGE);
  const [allLeaders, setAllLeaders] = useState(false);

  useEffect(() => {
    setLoading(true);
    api
      .themes(tf, CARD_BARS[tf])
      .then((r) => {
        setThemes(r.themes);
        setError(null);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [tf, version]);

  useEffect(() => setShown(PAGE), [tf]);

  const ranked = useMemo(() => sortThemes(themes, "score"), [themes]);
  const byScore = useMemo(() => (rankDir === "bottom" ? [...ranked].reverse() : ranked), [ranked, rankDir]);
  const visible = useMemo(() => {
    const sorted = sortThemes(filterThemes(themes, query), sort);
    return sort === "score" && rankDir === "bottom" ? [...sorted].reverse() : sorted;
  }, [themes, query, sort, rankDir]);
  const jumpTo = (e: MouseEvent<HTMLAnchorElement>, id: string) => {
    e.preventDefault();
    setQuery("");
    setShown(themes.length);
    window.setTimeout(() => document.getElementById(`theme-${id}`)?.scrollIntoView({ behavior: "smooth", block: "center" }), 50);
  };
  const leaders = allLeaders ? byScore : byScore.slice(0, LEADERS);
  const showBottom = () => {
    setRankDir("bottom");
    setSort("score");
    setAllLeaders(false);
    setShown(PAGE);
  };

  return (
    <div className="page">
      <section className="hero">
        <div>
          <h1>Themes</h1>
          <p className="muted">Groups of stocks that move together. Open a theme, or scan it in the Stock Scanner.</p>
        </div>
        <TfToggle tf={tf} onChange={setTf} />
      </section>

      <div className="card leaderboard">
        <div className="seg" role="group" aria-label="Score rank">
          <button type="button" className={rankDir === "top" ? "active" : ""} onClick={() => { setRankDir("top"); setAllLeaders(false); }}>
            Top 12
          </button>
          <button type="button" className={rankDir === "bottom" ? "active" : ""} onClick={showBottom}>
            Bottom 12
          </button>
        </div>
        <span className="muted small">{rankDir === "bottom" ? "Weakest → strongest:" : "Strongest → weakest:"}</span>
        {loading && themes.length === 0 && <LoadingIndicator label="Ranking…" className="small" />}
        {leaders.map((t, i) => (
          <a key={t.id} href={`#theme-${t.id}`} className={`lb-item ${t.row.mw_green ? "green" : "red"}`} onClick={(e) => jumpTo(e, t.id)}>
            <span className="muted">{i + 1}.</span> {t.name} <b>{t.row.score.toFixed(0)}</b>
          </a>
        ))}
        {ranked.length > LEADERS && (
          <button type="button" className="chip" onClick={() => setAllLeaders((v) => !v)}>
            {allLeaders ? (rankDir === "bottom" ? "show bottom 12" : "show top 12") : `show all ${ranked.length}`}
          </button>
        )}
      </div>

      <div className="card filters theme-tools">
        <input
          className="input search"
          placeholder="Find a theme or member ticker…"
          aria-label="Find a theme"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setShown(PAGE);
          }}
        />
        <div className="field">
          <span className="field-label">Sort by</span>
          <div className="seg" role="group" aria-label="Sort themes">
            {THEME_SORTS.map((s) => (
              <button key={s.key} className={s.key === sort ? "active" : ""} onClick={() => {
                  setSort(s.key);
                  setShown(PAGE);
                }}>
                {s.label}
              </button>
            ))}
          </div>
        </div>
        <span className="muted small theme-count">
          {query ? `${visible.length} of ${themes.length} themes` : `${themes.length} themes`}
        </span>
      </div>

      {error && <div className="banner error">{error}</div>}
      {loading && themes.length === 0 && <SkeletonCards count={9} label="Building theme indexes…" />}
      <div className="sector-grid theme-grid">
        {visible.slice(0, shown).map((t) => (
          <div key={t.id} id={`theme-${t.id}`}>
            <ThemeCard theme={t} />
          </div>
        ))}
      </div>
      {visible.length > shown && (
        <div className="show-more">
          <button className="btn" onClick={() => setShown((n) => n + PAGE)}>
            Show {Math.min(PAGE, visible.length - shown)} more themes ({visible.length - shown} left)
          </button>
        </div>
      )}
      {!loading && themes.length > 0 && visible.length === 0 && (
        <div className="card empty-state">No theme or member matches “{query}”.</div>
      )}
    </div>
  );
}
