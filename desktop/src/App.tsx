import { useState } from "react";

const sections = [
  { id: "library", label: "Library", mark: "▤", hint: "Select and scan folders" },
  { id: "compare", label: "Compare", mark: "⇄", hint: "Review library differences" },
  { id: "review", label: "Review & preview", mark: "◫", hint: "Resolve uncertain matches" },
  { id: "backups", label: "Backups & recovery", mark: "↺", hint: "Verified backups and recovery" },
  { id: "history", label: "Sync history", mark: "◷", hint: "Past operation reports" },
  { id: "health", label: "Library health", mark: "⌁", hint: "Metadata and file health" },
] as const;

type SectionId = (typeof sections)[number]["id"];

function App() {
  const [active, setActive] = useState<SectionId>("library");
  const section = sections.find((item) => item.id === active) ?? sections[0];

  return (
    <div className="app-frame">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">h.</div>
          <div>
            <div className="brand-name">harmelune</div>
            <div className="brand-caption">LOCAL MUSIC CARE</div>
          </div>
        </div>

        <div className="nav-label">WORKSPACE</div>
        <nav aria-label="Main navigation">
          {sections.map((item) => (
            <button
              className={`nav-item ${active === item.id ? "active" : ""}`}
              key={item.id}
              onClick={() => setActive(item.id)}
              aria-current={active === item.id ? "page" : undefined}
            >
              <span className="nav-mark" aria-hidden="true">{item.mark}</span>
              <span className="nav-copy">
                <span className="nav-title">{item.label}</span>
                <span className="nav-hint">{item.hint}</span>
              </span>
              {active === item.id && <span className="nav-indicator" />}
            </button>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <div className="local-status"><span className="status-dot" /> LOCAL-FIRST</div>
          <p>Your music stays on this device. No cloud library or account is required.</p>
          <div className="version">DESKTOP PREVIEW · 0.1</div>
        </div>
      </aside>

      <main className="main-panel">
        <header className="topbar">
          <div className="breadcrumb"><span>Workspace</span><span className="crumb-sep">/</span><strong>{section.label}</strong></div>
          <div className="topbar-status"><span className="status-dot muted" /> Python engine not connected</div>
        </header>

        <section className="page-content">
          <div className="eyebrow">HARMELUNE DESKTOP · MIGRATION PREVIEW</div>
          <div className="page-heading-row">
            <div>
              <h1>{active === "library" ? "Your music, in harmony." : section.label}</h1>
              <p className="page-subtitle">
                {active === "library"
                  ? "A calmer, clearer way to compare and care for your music libraries."
                  : section.hint + ". The existing Python engine remains authoritative."}
              </p>
            </div>
            <div className="read-only-pill"><span className="status-dot muted" /> SAFE PREVIEW</div>
          </div>

          <div className="notice" role="status">
            <div className="notice-icon" aria-hidden="true">i</div>
            <div>
              <strong>Migration foundation only</strong>
              <p>This interface is not connected to your music folders yet. Scanning, previews, and file-changing actions are intentionally unavailable until the restricted Python sidecar is wired and tested.</p>
            </div>
          </div>

          {active === "library" ? (
            <>
              <div className="section-title-row">
                <div>
                  <h2>Library workspace</h2>
                  <p>Choose two separate folders to begin. Nothing is scanned by this preview.</p>
                </div>
                <span className="subtle-label">NOT CONNECTED</span>
              </div>

              <div className="library-grid">
                <article className="library-card">
                  <div className="card-topline"><span className="library-letter">A</span><span className="card-state">NOT SELECTED</span></div>
                  <h3>Library A</h3>
                  <p className="path-placeholder">No folder selected</p>
                  <div className="card-footer"><span className="folder-mark">▱</span> Music source or destination</div>
                </article>
                <article className="library-card">
                  <div className="card-topline"><span className="library-letter second">B</span><span className="card-state">NOT SELECTED</span></div>
                  <h3>Library B</h3>
                  <p className="path-placeholder">No folder selected</p>
                  <div className="card-footer"><span className="folder-mark">▱</span> Music source or destination</div>
                </article>
              </div>

              <div className="section-title-row lower">
                <div>
                  <h2>Workflow</h2>
                  <p>The migration keeps review before every change.</p>
                </div>
              </div>
              <div className="workflow-list">
                <div className="workflow-step"><span className="step-number">01</span><div><strong>Select libraries</strong><p>Validate that the folders are separate and do not overlap.</p></div><span className="step-state">PENDING</span></div>
                <div className="workflow-step"><span className="step-number">02</span><div><strong>Scan & compare</strong><p>Read-only inventory with progress and health information.</p></div><span className="step-state">PENDING</span></div>
                <div className="workflow-step"><span className="step-number">03</span><div><strong>Review & preview</strong><p>Decide fuzzy matches and conflicts; inspect the exact operation list.</p></div><span className="step-state">PENDING</span></div>
                <div className="workflow-step"><span className="step-number">04</span><div><strong>Verified backup, then apply</strong><p>Safe first; Reconcile next; Mirror remains explicitly destructive.</p></div><span className="step-state">LOCKED</span></div>
              </div>
            </>
          ) : (
            <div className="empty-section">
              <div className="empty-icon" aria-hidden="true">{section.mark}</div>
              <h2>{section.label} is waiting for the Python bridge</h2>
              <p>{section.hint}. This section will be enabled only when the corresponding service and safety checks are available.</p>
              <button className="secondary-button" onClick={() => setActive("library")}>Back to library workspace</button>
            </div>
          )}

          <footer className="page-footer">
            <span><span className="status-dot" /> No library files have been accessed</span>
            <span>Python stays the sync engine · Tauri stays the desktop shell</span>
          </footer>
        </section>
      </main>
    </div>
  );
}

export default App;
