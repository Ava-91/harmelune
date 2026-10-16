import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { open } from "@tauri-apps/plugin-dialog";

const sections = [
  { id: "library", label: "Library", mark: "▤", hint: "Select and scan folders" },
  { id: "compare", label: "Compare", mark: "⇄", hint: "Review library differences" },
  { id: "review", label: "Review & preview", mark: "◫", hint: "Resolve uncertain matches" },
  { id: "backups", label: "Backups & recovery", mark: "↺", hint: "Verified backups and recovery" },
  { id: "history", label: "Sync history", mark: "◷", hint: "Past operation reports" },
  { id: "health", label: "Library health", mark: "⌁", hint: "Metadata and file health" },
] as const;
type SectionId = (typeof sections)[number]["id"];
type EngineResponse = { version: number; id: string | null; type: "result" | "error"; ok: boolean; result?: Record<string, any>; error?: { code: string; message: string } };
type Track = { path: string; name: string; title: string; artist: string; album: string; duration: number | null; size: number; side: string; sha256: string | null; artwork_count: number };
type ComparisonRow = { category: string; label: string; a: Track | null; b: Track | null; confidence?: number; confirmed?: boolean; metadata_conflict?: boolean; artwork_conflict?: boolean; reasons?: string[] };
type ScanSummary = { counts: Record<string, number>; library_a: string; library_b: string; tracks_a: number; tracks_b: number; errors_a: string[]; errors_b: string[]; enumeration_complete_a: boolean; enumeration_complete_b: boolean; unsupported_audio_a: number; unsupported_audio_b: number; safe_to_preview: boolean };
type ScanResult = { plan_id: string; summary: ScanSummary; page: { rows: ComparisonRow[]; total: number; has_more: boolean } };
const isTauri = () => typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

async function engineRequest(command: string, params: Record<string, unknown> = {}): Promise<EngineResponse> {
  return invoke<EngineResponse>("engine_request", {
    request: { version: 1, id: crypto.randomUUID(), command, params },
  });
}

function App() {
  const [active, setActive] = useState<SectionId>("library");
  const [engineStatus, setEngineStatus] = useState("Connecting to Python engine…");
  const [libraryA, setLibraryA] = useState("");
  const [libraryB, setLibraryB] = useState("");
  const [planId, setPlanId] = useState("");
  const [summary, setSummary] = useState<ScanSummary | null>(null);
  const [rows, setRows] = useState<ComparisonRow[]>([]);
  const [totalRows, setTotalRows] = useState(0);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("all");
  const [scanning, setScanning] = useState(false);
  const [progress, setProgress] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!isTauri()) {
      setEngineStatus("Open the Tauri desktop app to connect the local Python engine");
      return;
    }
    void engineRequest("hello").then((response) => {
      if (response.ok) setEngineStatus("Python engine ready · protocol v1");
      else setEngineStatus("Python engine returned an error");
    }).catch(() => setEngineStatus("Python engine not connected"));
    let unlisten: (() => void) | undefined;
    void listen<Record<string, unknown>>("engine-progress", (event) => {
      const payload = event.payload;
      if (payload.event === "scan_progress") {
        const side = payload.side === "a" ? "Library A" : "Library B";
        setProgress(`Scanning ${side} · ${String(payload.visited)} files visited`);
      }
    }).then((stop) => { unlisten = stop; });
    return () => { unlisten?.(); };
  }, []);

  useEffect(() => {
    if (!planId || !isTauri()) return;
    const timer = window.setTimeout(() => {
      void engineRequest("list_tracks", { plan_id: planId, offset: 0, limit: 100, query, category })
        .then((response) => {
          if (!response.ok) throw new Error(response.error?.message ?? "Could not load comparison rows.");
          const page = response.result as { rows: ComparisonRow[]; total: number };
          setRows(page.rows);
          setTotalRows(page.total);
        })
        .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : String(reason)));
    }, 180);
    return () => window.clearTimeout(timer);
  }, [planId, query, category]);

  const chooseFolder = async (which: "a" | "b") => {
    setError("");
    try {
      const selected = await open({ directory: true, multiple: false, title: which === "a" ? "Select Library A" : "Select Library B" });
      if (typeof selected !== "string") return;
      if (which === "a") setLibraryA(selected);
      else setLibraryB(selected);
      setPlanId("");
      setSummary(null);
      setRows([]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };

  const scan = async () => {
    if (!libraryA.trim() || !libraryB.trim()) {
      setError("Choose both Library A and Library B before scanning.");
      return;
    }
    if (libraryA.trim().toLocaleLowerCase() === libraryB.trim().toLocaleLowerCase()) {
      setError("Library A and Library B must be different folders.");
      return;
    }
    setError("");
    setScanning(true);
    setProgress("Starting read-only scan…");
    setActive("library");
    try {
      const response = await engineRequest("scan", { library_a: libraryA, library_b: libraryB });
      if (!response.ok) throw new Error(response.error?.message ?? "Scan failed.");
      const result = response.result as unknown as ScanResult;
      setPlanId(result.plan_id);
      setSummary(result.summary);
      setRows(result.page.rows);
      setTotalRows(result.page.total);
      setQuery("");
      setCategory("all");
      setActive("compare");
      setProgress(result.summary.safe_to_preview ? "Scan complete · no files changed" : "Scan has issues · review errors before proceeding");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setProgress("");
    } finally {
      setScanning(false);
    }
  };

  const section = sections.find((item) => item.id === active) ?? sections[0];
  const hasScan = Boolean(planId && summary);
  const selectedRows = rows;

  return (
    <div className="app-frame">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">h.</div>
          <div><div className="brand-name">harmelune</div><div className="brand-caption">LOCAL MUSIC CARE</div></div>
        </div>
        <div className="nav-label">WORKSPACE</div>
        <nav aria-label="Main navigation">
          {sections.map((item) => (
            <button className={`nav-item ${active === item.id ? "active" : ""}`} key={item.id}
              onClick={() => setActive(item.id)} aria-current={active === item.id ? "page" : undefined}>
              <span className="nav-mark" aria-hidden="true">{item.mark}</span>
              <span className="nav-copy"><span className="nav-title">{item.label}</span><span className="nav-hint">{item.hint}</span></span>
              {active === item.id && <span className="nav-indicator" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="local-status"><span className="status-dot" /> LOCAL-FIRST</div>
          <p>Your music stays on this device. The Python engine performs local scans; no cloud library is required.</p>
          <div className="version">DESKTOP PREVIEW · 0.2</div>
        </div>
      </aside>

      <main className="main-panel">
        <header className="topbar">
          <div className="breadcrumb"><span>Workspace</span><span className="crumb-sep">/</span><strong>{section.label}</strong></div>
          <div className="topbar-status"><span className={`status-dot ${engineStatus.includes("ready") ? "" : "muted"}`} /> {engineStatus}</div>
        </header>
        <section className="page-content">
          <div className="eyebrow">HARMELUNE DESKTOP · MIGRATION PREVIEW</div>
          <div className="page-heading-row">
            <div>
              <h1>{active === "library" ? "Your music, in harmony." : section.label}</h1>
              <p className="page-subtitle">{active === "library" ? "A calmer, clearer way to compare and care for your music libraries." : section.hint + ". The existing Python engine remains authoritative."}</p>
            </div>
            <div className="read-only-pill"><span className="status-dot muted" /> READ-ONLY PHASE</div>
          </div>

          <div className="notice" role="status">
            <div className="notice-icon" aria-hidden="true">i</div>
            <div><strong>File-changing actions are still locked</strong><p>The Python bridge currently supports read-only scanning and comparison. Review, dry-run, backups, and execution will be enabled only after their safety gates are ported and tested.</p></div>
          </div>

          {active === "library" && (
            <>
              <div className="section-title-row"><div><h2>Library workspace</h2><p>Choose two separate folders. Scanning reads metadata and hashes but does not change music files.</p></div><span className="subtle-label">{hasScan ? "SCAN AVAILABLE" : "READY TO SELECT"}</span></div>
              <div className="library-grid">
                <article className="library-card">
                  <div className="card-topline"><span className="library-letter">A</span><span className="card-state">{libraryA ? "FOLDER SELECTED" : "NOT SELECTED"}</span></div>
                  <h3>Library A</h3><p className="path-placeholder path-value">{libraryA || "No folder selected"}</p>
                  <button className="secondary-button" onClick={() => void chooseFolder("a")}>Choose folder…</button>
                  <div className="card-footer"><span className="folder-mark">▱</span> {summary ? `${summary.tracks_a} audio tracks found` : "Music source or destination"}</div>
                </article>
                <article className="library-card">
                  <div className="card-topline"><span className="library-letter second">B</span><span className="card-state">{libraryB ? "FOLDER SELECTED" : "NOT SELECTED"}</span></div>
                  <h3>Library B</h3><p className="path-placeholder path-value">{libraryB || "No folder selected"}</p>
                  <button className="secondary-button" onClick={() => void chooseFolder("b")}>Choose folder…</button>
                  <div className="card-footer"><span className="folder-mark">▱</span> {summary ? `${summary.tracks_b} audio tracks found` : "Music source or destination"}</div>
                </article>
              </div>
              <div className="scan-actions"><button className="primary-button" disabled={scanning || !isTauri()} onClick={() => void scan()}>{scanning ? "Scanning…" : "Scan & compare libraries"}</button><span>{progress || "Read-only scan · no backups or changes"}</span></div>
            </>
          )}

          {active === "compare" && (
            <>
              <div className="section-title-row"><div><h2>Comparison snapshot</h2><p>{summary ? `${summary.library_a}  ↔  ${summary.library_b}` : "Scan both libraries to populate the comparison."}</p></div><span className="subtle-label">{hasScan ? "READ-ONLY RESULTS" : "NO SCAN"}</span></div>
              {summary && <div className="metrics-grid">
                <div className="metric-card"><span>Library A</span><strong>{summary.tracks_a}</strong><small>audio tracks</small></div>
                <div className="metric-card"><span>Library B</span><strong>{summary.tracks_b}</strong><small>audio tracks</small></div>
                <div className="metric-card"><span>Confirmed</span><strong>{summary.counts.exact}</strong><small>matches</small></div>
                <div className="metric-card"><span>Needs review</span><strong>{summary.counts.fuzzy + summary.counts.conflicts}</strong><small>uncertain or conflicting</small></div>
              </div>}
              <div className="table-toolbar">
                <input aria-label="Search comparison" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search title, artist, album, or path…" disabled={!hasScan} />
                <select aria-label="Filter category" value={category} onChange={(event) => setCategory(event.target.value)} disabled={!hasScan}>
                  <option value="all">All categories</option><option value="exact">Confirmed</option><option value="fuzzy">Uncertain matches</option><option value="conflicts">Conflicts</option><option value="a_only">Only in A</option><option value="b_only">Only in B</option>
                </select>
              </div>
              {error && <div className="error-notice" role="alert">{error}</div>}
              <div className="comparison-table-wrap">
                <table className="comparison-table"><thead><tr><th>Category</th><th>Track</th><th>Artist</th><th>Album</th><th>Library A / B path</th><th>Match score</th></tr></thead>
                  <tbody>{selectedRows.map((row, index) => {
                    const primary = row.a ?? row.b;
                    const pathText = row.a && row.b ? `${row.a.path}\n↔ ${row.b.path}` : primary?.path ?? "—";
                    return <tr key={`${row.category}-${primary?.path ?? index}`}>
                      <td><span className={`category-pill category-${row.category}`}>{row.label}</span></td>
                      <td>{row.a && row.b ? `${row.a.title} ↔ ${row.b.title}` : primary?.title ?? "—"}</td>
                      <td>{row.a && row.b ? `${row.a.artist} / ${row.b.artist}` : primary?.artist ?? "—"}</td>
                      <td>{row.a && row.b ? `${row.a.album} / ${row.b.album}` : primary?.album ?? "—"}</td>
                      <td className="path-cell">{pathText}</td>
                      <td>{typeof row.confidence === "number" ? `${Math.round(row.confidence * 100)}%` : "—"}</td>
                    </tr>;
                  })}</tbody>
                </table>
                {!selectedRows.length && <div className="table-empty">{hasScan ? "No rows match these filters." : "Scan both libraries to see results."}</div>}
              </div>
              <div className="table-footer"><span>{totalRows} matching row(s) · showing up to 100</span><span>{summary?.safe_to_preview ? "No scan errors detected" : "Check scan warnings before proceeding"}</span></div>
              {summary && (summary.errors_a.length > 0 || summary.errors_b.length > 0) && <div className="error-notice"><strong>Scan warnings</strong><ul>{[...summary.errors_a, ...summary.errors_b].slice(0, 8).map((item, index) => <li key={index}>{item}</li>)}</ul></div>}
            </>
          )}

          {active !== "library" && active !== "compare" && (
            <div className="empty-section"><div className="empty-icon" aria-hidden="true">{section.mark}</div><h2>{section.label} is waiting for its safety workflow</h2><p>{section.hint}. This section remains unavailable until review, freshness validation, verified backups, and recovery behavior are connected to the Python engine.</p><button className="secondary-button" onClick={() => setActive("library")}>Back to library workspace</button></div>
          )}

          {error && active === "library" && <div className="error-notice" role="alert">{error}</div>}
          <footer className="page-footer"><span><span className="status-dot" /> {scanning ? progress : "Scan is read-only · no library files changed"}</span><span>Python stays the sync engine · Tauri stays the desktop shell</span></footer>
        </section>
      </main>
    </div>
  );
}
export default App;
