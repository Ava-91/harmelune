import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { open } from "@tauri-apps/plugin-dialog";

const sections = [
  { id: "library", label: "Library", mark: "▤", hint: "Select and scan folders" },
  { id: "compare", label: "Compare", mark: "⇄", hint: "Review library differences" },
  { id: "review", label: "Review & preview", mark: "◫", hint: "Resolve uncertain matches" },
  { id: "mirror", label: "Mirror", mark: "⇌", hint: "Review exact changes before mirroring" },
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
type SafePreview = { mode: string; status: string; preview_token?: string; operations: { kind: string; source: string | null; destination: string }[]; skipped: string[]; blocked: string[]; operation_count: number; mutations_enabled: boolean };
const isTauri = () => typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

async function engineRequest(command: string, params: Record<string, unknown> = {}): Promise<EngineResponse> {
  return invoke<EngineResponse>("engine_request", {
    request: { version: 1, id: crypto.randomUUID(), command, params },
  });
}

function PreviewPanel({ preview }: { preview: SafePreview }) {
  return (
    <div className="preview-result">
      <div className="metrics-grid">
        <div className="metric-card"><span>Planned operations</span><strong>{preview.operation_count}</strong><small>no files changed</small></div>
        <div className="metric-card"><span>Skipped</span><strong>{preview.skipped.length}</strong><small>explicitly left untouched</small></div>
        <div className="metric-card"><span>Blocked</span><strong>{preview.blocked.length}</strong><small>requires attention</small></div>
        <div className="metric-card"><span>Engine status</span><strong>{preview.status}</strong><small>{preview.mode} dry-run result</small></div>
      </div>
      <div className="notice"><div className="notice-icon">i</div><div><strong>Preview only — nothing has changed yet</strong><p>This preview itself performs no copy, replace, delete, backup, or restore action.</p></div></div>
      <h3 className="preview-list-title">Planned operations {preview.operations.length > 20 ? "(first 20 shown)" : ""}</h3>
      {preview.operations.length ? <ul className="preview-list">{preview.operations.slice(0, 20).map((operation, index) => <li key={index}><span className="operation-kind">{operation.kind}</span><span className="operation-path">{operation.source ?? "—"}<span>→ {operation.destination}</span></span></li>)}</ul> : <div className="table-empty">No operations are planned for this preview.</div>}
      {preview.blocked.length > 0 && <div className="error-notice"><strong>Blocked items</strong><ul>{preview.blocked.slice(0, 20).map((item, index) => <li key={index}>{item}</li>)}</ul></div>}
      {preview.skipped.length > 0 && <div className="notice"><div className="notice-icon">i</div><div><strong>Skipped items</strong><ul>{preview.skipped.slice(0, 20).map((item, index) => <li key={index}>{item}</li>)}</ul></div></div>}
    </div>
  );
}

function App() {
  const [active, setActive] = useState<SectionId>("library");
  const [engineStatus, setEngineStatus] = useState("Connecting to Python engine…");
  const [libraryA, setLibraryA] = useState("");
  const [libraryB, setLibraryB] = useState("");
  const [planId, setPlanId] = useState("");
  const [masterLibrary, setMasterLibrary] = useState("library_a");
  const [preview, setPreview] = useState<SafePreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [safeBackupRoot, setSafeBackupRoot] = useState("");
  const [safeConfirmation, setSafeConfirmation] = useState("");
  const [safeExecuting, setSafeExecuting] = useState(false);
  const [executionReport, setExecutionReport] = useState<Record<string, any> | null>(null);
  const [reconcileDecisions, setReconcileDecisions] = useState<Record<string, string>>({});
  const [backupRoot, setBackupRoot] = useState("");
  const [reconcilePreview, setReconcilePreview] = useState<SafePreview | null>(null);
  const [reconcilePreviewing, setReconcilePreviewing] = useState(false);
  const [reconcileConfirmation, setReconcileConfirmation] = useState("");
  const [reconcileExecuting, setReconcileExecuting] = useState(false);
  const [reconcileReport, setReconcileReport] = useState<Record<string, any> | null>(null);
  const [mirrorMasterLibrary, setMirrorMasterLibrary] = useState("library_a");
  const [mirrorBackupRoot, setMirrorBackupRoot] = useState("");
  const [mirrorPreview, setMirrorPreview] = useState<SafePreview | null>(null);
  const [mirrorPreviewing, setMirrorPreviewing] = useState(false);
  const [mirrorConfirmation, setMirrorConfirmation] = useState("");
  const [mirrorExecuting, setMirrorExecuting] = useState(false);
  const [mirrorReport, setMirrorReport] = useState<Record<string, any> | null>(null);
  const [reviewRows, setReviewRows] = useState<ComparisonRow[]>([]);
  const [reviewPage, setReviewPage] = useState(0);
  const [reviewTotal, setReviewTotal] = useState(0);
  const [stalePlan, setStalePlan] = useState(false);
  const [summary, setSummary] = useState<ScanSummary | null>(null);
  const [rows, setRows] = useState<ComparisonRow[]>([]);
  const [totalRows, setTotalRows] = useState(0);
  const [pageIndex, setPageIndex] = useState(0);
  const requestSequence = useRef(0);
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
    const sequence = ++requestSequence.current;
    const timer = window.setTimeout(() => {
      void engineRequest("list_tracks", { plan_id: planId, offset: pageIndex * 100, limit: 100, query, category })
        .then((response) => {
          if (sequence !== requestSequence.current) return;
          if (!response.ok) throw new Error(response.error?.message ?? "Could not load comparison rows.");
          const page = response.result as { rows: ComparisonRow[]; total: number };
          setRows(page.rows);
          setTotalRows(page.total);
          setError("");
        })
        .catch((reason: unknown) => {
          if (sequence === requestSequence.current) setError(reason instanceof Error ? reason.message : String(reason));
        });
    }, 180);
    return () => {
      window.clearTimeout(timer);
      requestSequence.current += 1;
    };
  }, [planId, query, category, pageIndex]);

  useEffect(() => {
    if (active !== "review" || !planId || !isTauri()) return;
    let cancelled = false;
    void engineRequest("list_tracks", { plan_id: planId, offset: reviewPage * 100, limit: 100, category: "all", query: "" })
      .then((response) => {
        if (cancelled) return;
        if (!response.ok) throw new Error(response.error?.message ?? "Could not load review items.");
        const page = response.result as { rows: ComparisonRow[]; total: number };
        setReviewRows(page.rows);
        setReviewTotal(page.total);
      })
      .catch((reason) => {
        if (!cancelled) {
          setReviewRows([]);
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      });
    return () => { cancelled = true; };
  }, [active, planId, reviewPage]);

  const chooseFolder = async (which: "a" | "b") => {
    setError("");
    try {
      const selected = await open({ directory: true, multiple: false, title: which === "a" ? "Select Library A" : "Select Library B" });
      if (typeof selected !== "string") return;
      if (which === "a") setLibraryA(selected);
      else setLibraryB(selected);
      setPlanId("");
      setSummary(null);
      setPreview(null);
      setReconcilePreview(null);
      setReconcileDecisions({});
      setReconcileConfirmation("");
      setReconcileReport(null);
      setMirrorPreview(null);
      setMirrorConfirmation("");
      setMirrorReport(null);
      setSafeConfirmation("");
      setExecutionReport(null);
      setStalePlan(false);
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
      setPreview(null);
      setReconcilePreview(null);
      setReconcileDecisions({});
      setReconcileConfirmation("");
      setReconcileReport(null);
      setMirrorPreview(null);
      setMirrorConfirmation("");
      setMirrorReport(null);
      setSafeConfirmation("");
      setExecutionReport(null);
      setStalePlan(false);
      setReviewPage(0);
      setRows(result.page.rows);
      setTotalRows(result.page.total);
      setPageIndex(0);
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

  const buildSafePreview = async () => {
    if (!planId || !summary) {
      setError("Scan both libraries before building a preview.");
      return;
    }
    if (!summary.safe_to_preview) {
      setError("Preview is blocked because one or both scans have errors or are incomplete.");
      return;
    }
    setError("");
    setStalePlan(false);
    setPreviewing(true);
    try {
      const response = await engineRequest("preview_safe", { plan_id: planId, master_library: masterLibrary });
      if (!response.ok) {
        setStalePlan(response.error?.code === "STALE_PLAN" || response.error?.code === "PLAN_NOT_FOUND");
        throw new Error(response.error?.message ?? "Could not build the dry-run preview.");
      }
      setPreview(response.result as unknown as SafePreview);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setPreview(null);
    } finally {
      setPreviewing(false);
    }
  };


  const executeSafe = async () => {
    if (!planId || !preview?.preview_token || !summary || !safeBackupRoot.trim()) {
      setError("Build a fresh Safe preview and choose a separate backup location first.");
      return;
    }
    if (safeConfirmation !== "APPLY SAFE") {
      setError('Type APPLY SAFE exactly to authorize the reviewed copy-only operation.');
      return;
    }
    if (preview.status !== "SUCCESS" || preview.blocked.length || preview.operations.some((operation) => operation.kind !== "copy")) {
      setError("Execution blocked: the current preview is not an unblocked copy-only plan.");
      return;
    }
    setError("");
    setSafeExecuting(true);
    try {
      const response = await engineRequest("execute_safe", {
        plan_id: planId,
        master_library: masterLibrary,
        backup_root: safeBackupRoot.trim(),
        confirmation: safeConfirmation,
        preview_token: preview.preview_token,
      });
      if (!response.ok) {
        setStalePlan(response.error?.code === "STALE_PLAN" || response.error?.code === "PLAN_NOT_FOUND" || response.error?.code === "PREVIEW_MISMATCH");
        throw new Error(response.error?.message ?? "Safe execution was blocked.");
      }
      setExecutionReport((response.result as Record<string, any>).execution);
      setPreview(null);
      setSafeConfirmation("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSafeExecuting(false);
    }
  };

  const setDecision = (row: ComparisonRow, value: string) => {
    const key = row.category === "a_only" ? `a-only:${row.a?.path ?? ""}`
      : row.category === "b_only" ? `b-only:${row.b?.path ?? ""}`
      : `match:${row.a?.path ?? ""}`;
    setReconcileDecisions((current) => {
      const next = { ...current };
      if (value) next[key] = value;
      else delete next[key];
      return next;
    });
    setReconcilePreview(null);
    setReconcileConfirmation("");
    setReconcileReport(null);
    setError("");
  };

  const buildReconcilePreview = async () => {
    if (!planId || !summary) {
      setError("Scan both libraries before building a Reconcile preview.");
      return;
    }
    if (!summary.safe_to_preview) {
      setError("Reconcile preview is blocked because one or both scans have errors or are incomplete.");
      return;
    }
    if (!backupRoot.trim()) {
      setError("Choose a separate backup location before previewing Reconcile.");
      return;
    }
    setError("");
    setStalePlan(false);
    setReconcilePreviewing(true);
    try {
      const response = await engineRequest("preview_reconcile", {
        plan_id: planId,
        decisions: reconcileDecisions,
        backup_root: backupRoot.trim(),
      });
      if (!response.ok) {
        setStalePlan(response.error?.code === "STALE_PLAN" || response.error?.code === "PLAN_NOT_FOUND");
        throw new Error(response.error?.message ?? "Could not build the Reconcile preview.");
      }
      setReconcilePreview(response.result as unknown as SafePreview);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setReconcilePreview(null);
    } finally {
      setReconcilePreviewing(false);
    }
  };

  const executeReconcile = async () => {
    if (!planId || !summary || !reconcilePreview?.preview_token || !backupRoot.trim()) {
      setError("Build a fresh Reconcile preview and choose a separate backup location first.");
      return;
    }
    if (reconcileConfirmation !== "APPLY RECONCILE") {
      setError('Type APPLY RECONCILE exactly to authorize the reviewed Reconcile operations.');
      return;
    }
    if (reconcilePreview.status !== "SUCCESS" || reconcilePreview.blocked.length || reconcilePreview.operations.some((operation) => !["copy", "replace"].includes(operation.kind))) {
      setError("Reconcile execution is blocked until the preview is successful, unblocked, and contains only explicit copy/replace operations.");
      return;
    }
    setError("");
    setReconcileExecuting(true);
    try {
      const response = await engineRequest("execute_reconcile", {
        plan_id: planId, backup_root: backupRoot.trim(), decisions: reconcileDecisions,
        preview_token: reconcilePreview.preview_token, confirmation: reconcileConfirmation,
      });
      if (!response.ok) {
        setStalePlan(["STALE_PLAN", "PLAN_NOT_FOUND", "PREVIEW_MISMATCH"].includes(response.error?.code ?? ""));
        throw new Error(response.error?.message ?? "Reconcile execution was blocked.");
      }
      setReconcileReport((response.result as Record<string, any>).execution);
      setReconcilePreview(null);
      setReconcileConfirmation("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setReconcileExecuting(false);
    }
  };
  const buildMirrorPreview = async () => {
    if (!planId || !summary) {
      setError("Scan both libraries before building a Mirror preview.");
      return;
    }
    if (!summary.safe_to_preview) {
      setError("Mirror is blocked because one or both scans have errors or are incomplete.");
      return;
    }
    if (!mirrorBackupRoot.trim()) {
      setError("Choose a separate backup location outside both libraries first.");
      return;
    }
    setError("");
    setStalePlan(false);
    setMirrorPreviewing(true);
    setMirrorPreview(null);
    setMirrorConfirmation("");
    setMirrorReport(null);
    try {
      const response = await engineRequest("preview_mirror", {
        plan_id: planId,
        master_library: mirrorMasterLibrary,
        backup_root: mirrorBackupRoot.trim(),
      });
      if (!response.ok) {
        setStalePlan(["STALE_PLAN", "PLAN_NOT_FOUND"].includes(response.error?.code ?? ""));
        throw new Error(response.error?.message ?? "Could not build the Mirror preview.");
      }
      setMirrorPreview(response.result as unknown as SafePreview);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setMirrorPreviewing(false);
    }
  };

  const executeMirror = async () => {
    if (!planId || !summary || !mirrorPreview?.preview_token || !mirrorBackupRoot.trim()) {
      setError("Build a fresh Mirror preview and choose a separate backup location first.");
      return;
    }
    if (mirrorConfirmation !== "MIRROR") {
      setError('Type MIRROR exactly to authorize the destructive Mirror operation.');
      return;
    }
    if (mirrorPreview.status !== "SUCCESS" || mirrorPreview.blocked.length ||
        mirrorPreview.operations.some((operation) => !["copy", "replace", "delete"].includes(operation.kind))) {
      setError("Mirror execution is blocked until the preview is successful, unblocked, and contains only supported operations.");
      return;
    }
    setError("");
    setMirrorExecuting(true);
    try {
      const response = await engineRequest("execute_mirror", {
        plan_id: planId,
        master_library: mirrorMasterLibrary,
        backup_root: mirrorBackupRoot.trim(),
        preview_token: mirrorPreview.preview_token,
        confirmation: mirrorConfirmation,
      });
      if (!response.ok) {
        setStalePlan(["STALE_PLAN", "PLAN_NOT_FOUND", "PREVIEW_MISMATCH"].includes(response.error?.code ?? ""));
        throw new Error(response.error?.message ?? "Mirror execution was blocked.");
      }
      setMirrorReport((response.result as Record<string, any>).execution);
      setMirrorPreview(null);
      setMirrorConfirmation("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setMirrorExecuting(false);
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
            <div className="read-only-pill"><span className="status-dot muted" /> SAFE + RECONCILE GATED</div>
          </div>

          <div className="notice" role="status">
            <div className="notice-icon" aria-hidden="true">i</div>
            <div><strong>Safe and Reconcile execution require explicit approval</strong><p>Both workflows require a fresh preview, exact typed confirmation, and verified backups outside both libraries. Reconcile applies only the saved explicit decisions. Mirror and Restore remain locked.</p></div>
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
              {summary && <div className="health-grid" aria-label="Library scan health">
                <div className={summary.enumeration_complete_a && summary.errors_a.length === 0 ? "health-card healthy" : "health-card warning"}>
                  <span>Library A health</span><strong>{summary.enumeration_complete_a && summary.errors_a.length === 0 ? "Complete scan" : "Needs attention"}</strong>
                  <small>{summary.errors_a.length} scan error(s) · {summary.unsupported_audio_a} unsupported audio-like file(s)</small>
                </div>
                <div className={summary.enumeration_complete_b && summary.errors_b.length === 0 ? "health-card healthy" : "health-card warning"}>
                  <span>Library B health</span><strong>{summary.enumeration_complete_b && summary.errors_b.length === 0 ? "Complete scan" : "Needs attention"}</strong>
                  <small>{summary.errors_b.length} scan error(s) · {summary.unsupported_audio_b} unsupported audio-like file(s)</small>
                </div>
              </div>}
              <div className="table-toolbar">
                <input aria-label="Search comparison" value={query} onChange={(event) => { setQuery(event.target.value); setPageIndex(0); }} placeholder="Search title, artist, album, or path…" disabled={!hasScan} />
                <select aria-label="Filter category" value={category} onChange={(event) => { setCategory(event.target.value); setPageIndex(0); }} disabled={!hasScan}>
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
              <div className="table-footer">
                <span>Page {Math.min(pageIndex + 1, Math.max(1, Math.ceil(totalRows / 100)))} of {Math.max(1, Math.ceil(totalRows / 100))} · {totalRows} matching row(s)</span>
                <div className="page-controls">
                  <button type="button" className="secondary-button page-button" disabled={pageIndex === 0 || !hasScan} onClick={() => setPageIndex((current) => Math.max(0, current - 1))}>Previous</button>
                  <button type="button" className="secondary-button page-button" disabled={!hasScan || pageIndex + 1 >= Math.ceil(totalRows / 100)} onClick={() => setPageIndex((current) => current + 1)}>Next</button>
                </div>
                <span>{summary?.safe_to_preview ? "No scan errors detected" : "Check scan warnings before proceeding"}</span>
              </div>
              {summary && (summary.errors_a.length > 0 || summary.errors_b.length > 0) && <div className="error-notice"><strong>Scan warnings</strong><ul>{[...summary.errors_a, ...summary.errors_b].slice(0, 8).map((item, index) => <li key={index}>{item}</li>)}</ul></div>}
            </>
          )}

          {active === "review" && (
            <>
              <div className="section-title-row"><div><h2>Safe-mode dry run</h2><p>Preview the Python engine's planned copy operations. This never writes to either library.</p></div><span className="subtle-label">NO FILE CHANGES</span></div>
              <div className="preview-controls">
                <label htmlFor="master-library">Copy source (master library)</label>
                <select id="master-library" value={masterLibrary} onChange={(event) => { setMasterLibrary(event.target.value); setPreview(null); }}>
                  <option value="library_a">Library A → Library B</option><option value="library_b">Library B → Library A</option>
                </select>
                <button className="primary-button" disabled={!hasScan || !summary?.safe_to_preview || previewing || !isTauri()} onClick={() => void buildSafePreview()}>{previewing ? "Building preview…" : "Build safe-mode preview"}</button>
              </div>
              {!summary && <div className="table-empty">Scan both libraries first. No preview can be built without a current scan.</div>}
              {summary && !summary.safe_to_preview && <div className="error-notice">Preview blocked: resolve scan errors or incomplete enumeration, then scan again.</div>}

              {preview && <PreviewPanel preview={preview} />}
              {preview && (
                <div className="reconcile-backup safe-execution-panel">
                  <h3>Safe execution — final safety gate</h3>
                  <p>Only the exact preview below can be applied. Harmelune rechecks freshness, requires a verified backup outside both libraries, and permits copy-only operations. Existing files are never overwritten or deleted.</p>
                  <label htmlFor="safe-backup-root">Separate backup location (outside Library A and Library B)</label>
                  <input id="safe-backup-root" value={safeBackupRoot} onChange={(event) => setSafeBackupRoot(event.target.value)} placeholder="For example, a separate backup drive/folder…" />
                  <label htmlFor="safe-confirmation">Type <strong>APPLY SAFE</strong> to authorize execution</label>
                  <input id="safe-confirmation" value={safeConfirmation} onChange={(event) => setSafeConfirmation(event.target.value)} placeholder="APPLY SAFE" autoComplete="off" />
                  <button className="primary-button" disabled={!hasScan || !preview.preview_token || preview.status !== "SUCCESS" || preview.blocked.length > 0 || preview.operations.some((operation) => operation.kind !== "copy") || !safeBackupRoot.trim() || safeConfirmation !== "APPLY SAFE" || safeExecuting || !isTauri()} onClick={() => void executeSafe()}>{safeExecuting ? "Creating verified backup and copying…" : "Create verified backup & apply Safe copies"}</button>
                  <small>This will modify Library B or Library A according to the selected direction. It is intentionally a separate, explicit action.</small>
                </div>
              )}
              {executionReport && (
                <div className="preview-result execution-report">
                  <h3>Safe execution report</h3>
                  <div className="metrics-grid">
                    <div className="metric-card"><span>Final status</span><strong>{String(executionReport.final_status)}</strong></div>
                    <div className="metric-card"><span>Copied</span><strong>{Number(executionReport.succeeded ?? 0)}</strong></div>
                    <div className="metric-card"><span>Skipped</span><strong>{Number(executionReport.skipped ?? 0)}</strong></div>
                    <div className="metric-card"><span>Failed</span><strong>{Number(executionReport.failed ?? 0)}</strong></div>
                  </div>
                  <p>Verified backup(s): {(executionReport.backups ?? []).join(", ") || "No backup was needed because there were no copy operations."}</p>
                  <details><summary>Full execution report</summary><pre>{JSON.stringify(executionReport, null, 2)}</pre></details>
                </div>
              )}
              <div className="section-title-row reconcile-heading"><div><h2>Reconcile review</h2><p>Choose a decision for each unmatched track and each uncertain or conflicting match. No choice is applied automatically.</p></div><span className="subtle-label">{Object.keys(reconcileDecisions).length} DECISIONS SAVED</span></div>
              <div className="reconcile-intro">
                <span>{summary ? `${summary.counts.a_only + summary.counts.b_only + summary.counts.fuzzy + summary.counts.conflicts} item(s) require an explicit decision across the scan` : "Scan libraries to load review items."}</span>
                <span>Review page {reviewPage + 1} of {Math.max(1, Math.ceil(reviewTotal / 100))}</span>
              </div>
              <div className="review-items">
                {reviewRows.filter((row) => row.category !== "exact" || row.metadata_conflict || row.artwork_conflict).map((row, index) => {
                  const key = row.category === "a_only" ? `a-only:${row.a?.path ?? ""}`
                    : row.category === "b_only" ? `b-only:${row.b?.path ?? ""}`
                    : `match:${row.a?.path ?? ""}`;
                  const selected = reconcileDecisions[key] ?? "";
                  const trackA = row.a;
                  const trackB = row.b;
                  const title = trackA && trackB ? `${trackA.title} ↔ ${trackB.title}` : (trackA ?? trackB)?.title ?? "Unknown track";
                  const detail = trackA && trackB ? `${trackA.artist} / ${trackB.artist}` : (trackA ?? trackB)?.artist ?? "";
                  const matchNeedsDecision = row.category === "fuzzy" || row.category === "conflicts" || Boolean(row.metadata_conflict) || Boolean(row.artwork_conflict);
                  return (
                    <article className="review-item" key={key || index}>
                      <div className="review-item-main">
                        <span className={`category-pill category-${row.category}`}>{row.label}</span>
                        <strong>{title}</strong><span className="review-artist">{detail}</span>
                        {typeof row.confidence === "number" && <span className="review-reason">Match confidence: {Math.round(row.confidence * 100)}%</span>}
                        {row.metadata_conflict && <span className="review-reason conflict">Metadata differs between libraries</span>}
                        {row.artwork_conflict && <span className="review-reason conflict">Artwork differs between libraries</span>}
                        {(row.reasons ?? []).map((reason, reasonIndex) => <span className="review-reason" key={reasonIndex}>{reason}</span>)}
                        <span className="review-path">{trackA?.path ?? "—"}{trackB ? ` ↔ ${trackB.path}` : ""}</span>
                      </div>
                      <label className="decision-label">Decision
                        <select value={selected} onChange={(event) => setDecision(row, event.target.value)}>
                          <option value="">Choose explicitly…</option>
                          {row.category === "a_only" && <><option value="copy_a_to_b">Copy A → B</option><option value="skip">Keep separate / skip</option></>}
                          {row.category === "b_only" && <><option value="copy_b_to_a">Copy B → A</option><option value="skip">Keep separate / skip</option></>}
                          {matchNeedsDecision && <><option value="keep_a">Keep Library A version</option><option value="keep_b">Keep Library B version</option><option value="skip">Keep both / skip</option></>}
                        </select>
                      </label>
                    </article>
                  );
                })}
                {!reviewRows.some((row) => row.category !== "exact" || row.metadata_conflict || row.artwork_conflict) && <div className="table-empty">No review items on this page.</div>}
              </div>
              <div className="page-controls review-pagination">
                <button className="secondary-button page-button" disabled={reviewPage === 0} onClick={() => setReviewPage((page) => Math.max(0, page - 1))}>Previous review page</button>
                <button className="secondary-button page-button" disabled={(reviewPage + 1) * 100 >= reviewTotal} onClick={() => setReviewPage((page) => page + 1)}>Next review page</button>
              </div>
              <div className="reconcile-backup">
                <label htmlFor="backup-root">Separate backup location (required)</label>
                <input id="backup-root" value={backupRoot} onChange={(event) => { setBackupRoot(event.target.value); setReconcilePreview(null); setReconcileConfirmation(""); setReconcileReport(null); }} placeholder="Choose a folder outside both music libraries…" />
                <small>Preview validates this location but does not create a backup or modify any file.</small>
                <button className="primary-button" disabled={!hasScan || !summary?.safe_to_preview || reconcilePreviewing || !isTauri()} onClick={() => void buildReconcilePreview()}>{reconcilePreviewing ? "Building Reconcile preview…" : "Build Reconcile dry run"}</button>
              </div>
                            {reconcilePreview && <PreviewPanel preview={reconcilePreview} />}
              {reconcilePreview && (
                <div className="reconcile-backup safe-execution-panel">
                  <h3>Reconcile execution — final safety gate</h3>
                  <p>This applies only the explicit decisions shown in this preview. Copy operations add missing files; replace operations replace the selected counterpart only after verified backups. No delete operation is permitted.</p>
                  <label htmlFor="reconcile-confirmation">Type <strong>APPLY RECONCILE</strong> to authorize execution</label>
                  <input id="reconcile-confirmation" value={reconcileConfirmation} onChange={(event) => setReconcileConfirmation(event.target.value)} placeholder="APPLY RECONCILE" autoComplete="off" />
                  <button className="primary-button" disabled={!hasScan || !reconcilePreview.preview_token || reconcilePreview.status !== "SUCCESS" || reconcilePreview.blocked.length > 0 || reconcilePreview.operations.some((operation) => !["copy", "replace"].includes(operation.kind)) || !backupRoot.trim() || reconcileConfirmation !== "APPLY RECONCILE" || reconcileExecuting || !isTauri()} onClick={() => void executeReconcile()}>{reconcileExecuting ? "Creating verified backups and applying decisions…" : "Create verified backups & apply Reconcile decisions"}</button>
                  <small>Any missing decision, changed library, changed decision, changed backup location, or altered preview blocks execution and requires a fresh preview.</small>
                </div>
              )}
              {reconcileReport && (
                <div className="preview-result execution-report">
                  <h3>Reconcile execution report</h3>
                  <div className="metrics-grid">
                    <div className="metric-card"><span>Final status</span><strong>{String(reconcileReport.final_status)}</strong></div>
                    <div className="metric-card"><span>Applied</span><strong>{Number(reconcileReport.succeeded ?? 0)}</strong></div>
                    <div className="metric-card"><span>Skipped</span><strong>{Number(reconcileReport.skipped ?? 0)}</strong></div>
                    <div className="metric-card"><span>Failed</span><strong>{Number(reconcileReport.failed ?? 0)}</strong></div>
                  </div>
                  <p>Verified backups: {(reconcileReport.backups ?? []).join(", ") || "No backup was needed because no file changes were selected."}</p>
                  <details><summary>Full execution report</summary><pre>{JSON.stringify(reconcileReport, null, 2)}</pre></details>
                </div>
              )}
              {stalePlan && <div className="error-notice stale-notice"><strong>Plan is stale</strong><p>One or both libraries changed after scanning. Rescan before reviewing or previewing again.</p><button className="secondary-button" onClick={() => void scan()}>Rescan libraries</button></div>}
              {error && <div className="error-notice" role="alert">{error}</div>}
            </>
          )}

          {active === "mirror" && (
            <>
              <div className="section-title-row">
                <div><h2>Mirror — destructive synchronization</h2><p>Make the destination match the selected master. Every copy, replacement, and deletion must be visible before approval.</p></div>
                <span className="subtle-label">EXPLICIT DELETION GATE</span>
              </div>
              <div className="preview-controls">
                <label htmlFor="mirror-master">Master library</label>
                <select id="mirror-master" value={mirrorMasterLibrary} onChange={(event) => {
                  setMirrorMasterLibrary(event.target.value);
                  setMirrorPreview(null);
                  setMirrorConfirmation("");
                  setMirrorReport(null);
                }}>
                  <option value="library_a">Library A → Library B (B becomes mirror)</option>
                  <option value="library_b">Library B → Library A (A becomes mirror)</option>
                </select>
              </div>
              <div className="reconcile-backup">
                <label htmlFor="mirror-backup-root">Separate backup location — outside BOTH libraries</label>
                <input id="mirror-backup-root" value={mirrorBackupRoot} onChange={(event) => {
                  setMirrorBackupRoot(event.target.value);
                  setMirrorPreview(null);
                  setMirrorConfirmation("");
                  setMirrorReport(null);
                }} placeholder="Choose a separate backup drive/folder…" />
                <small>Mirror cannot execute with an incomplete scan, stale plan, changed backup location, or changed preview.</small>
                <button className="primary-button" disabled={!hasScan || !summary?.safe_to_preview || !mirrorBackupRoot.trim() || mirrorPreviewing || !isTauri()} onClick={() => void buildMirrorPreview()}>
                  {mirrorPreviewing ? "Building Mirror preview…" : "Build Mirror dry run"}
                </button>
              </div>
              {!hasScan && <div className="table-empty">Scan both libraries before planning Mirror.</div>}
              {summary && !summary.safe_to_preview && <div className="error-notice">Mirror blocked: both scans must finish without errors before a preview can be approved.</div>}
              {mirrorPreview && (
                <div className="preview-result">
                  <div className="metrics-grid">
                    <div className="metric-card"><span>All operations</span><strong>{mirrorPreview.operation_count}</strong><small>full list below</small></div>
                    <div className="metric-card"><span>Deletions</span><strong>{mirrorPreview.operations.filter((operation) => operation.kind === "delete").length}</strong><small>destination files removed</small></div>
                    <div className="metric-card"><span>Replacements</span><strong>{mirrorPreview.operations.filter((operation) => operation.kind === "replace").length}</strong><small>destination files replaced</small></div>
                    <div className="metric-card"><span>Preview status</span><strong>{mirrorPreview.status}</strong><small>{mirrorPreview.blocked.length} blocker(s)</small></div>
                  </div>
                  <div className="error-notice">
                    <strong>Review every planned mutation</strong>
                    <p>Nothing has changed yet. The complete operation list is shown here, not truncated. Read the delete and replacement destinations carefully.</p>
                  </div>
                  <h3 className="preview-list-title">Exact planned operations ({mirrorPreview.operations.length})</h3>
                  {mirrorPreview.operations.length ? (
                    <ul className="preview-list">{mirrorPreview.operations.map((operation, index) => (
                      <li key={index}>
                        <span className="operation-kind">{operation.kind.toUpperCase()}</span>
                        <span className="operation-path">{operation.source ?? "—"}<span>→ {operation.destination}</span></span>
                      </li>
                    ))}</ul>
                  ) : <div className="table-empty">No operations are planned; Mirror has nothing to change.</div>}
                  {mirrorPreview.blocked.length > 0 && <div className="error-notice"><strong>Blocked items — execution unavailable</strong><ul>{mirrorPreview.blocked.map((item, index) => <li key={index}>{item}</li>)}</ul></div>}
                  {mirrorPreview.operations.some((operation) => operation.kind === "delete") && (
                    <div className="error-notice">
                      <strong>Exact deletion list ({mirrorPreview.operations.filter((operation) => operation.kind === "delete").length})</strong>
                      <ul>{mirrorPreview.operations.filter((operation) => operation.kind === "delete").map((operation, index) => <li key={index}><code>{operation.destination}</code></li>)}</ul>
                    </div>
                  )}
                  {mirrorPreview.operations.some((operation) => operation.kind === "replace") && (
                    <div className="notice"><div className="notice-icon">!</div><div><strong>Exact replacement list ({mirrorPreview.operations.filter((operation) => operation.kind === "replace").length})</strong><ul>{mirrorPreview.operations.filter((operation) => operation.kind === "replace").map((operation, index) => <li key={index}><code>{operation.destination}</code> ← {operation.source}</li>)}</ul></div></div>
                  )}
                  <div className="reconcile-backup safe-execution-panel">
                    <h3>Mirror execution — final destructive gate</h3>
                    <p>Before any destination changes, Harmelune creates and verifies a backup of the destination library. The Python transaction engine rechecks freshness and performs the approved plan.</p>
                    <label htmlFor="mirror-confirmation">Type <strong>MIRROR</strong> exactly to authorize every listed operation, including deletions</label>
                    <input id="mirror-confirmation" value={mirrorConfirmation} onChange={(event) => setMirrorConfirmation(event.target.value)} placeholder="MIRROR" autoComplete="off" />
                    <button className="primary-button" disabled={!hasScan || !mirrorPreview.preview_token || mirrorPreview.status !== "SUCCESS" || mirrorPreview.blocked.length > 0 || !mirrorPreview.operations.length || !mirrorBackupRoot.trim() || mirrorConfirmation !== "MIRROR" || mirrorExecuting || !isTauri()} onClick={() => void executeMirror()}>
                      {mirrorExecuting ? "Verifying destination backup and applying Mirror…" : "Create verified backup & execute Mirror"}
                    </button>
                    <small>Changing the direction or backup folder invalidates this preview. Any stale or altered plan requires a new scan and approval.</small>
                  </div>
                </div>
              )}
              {mirrorReport && (
                <div className="preview-result execution-report">
                  <h3>Mirror execution report</h3>
                  <div className="metrics-grid">
                    <div className="metric-card"><span>Final status</span><strong>{String(mirrorReport.final_status)}</strong></div>
                    <div className="metric-card"><span>Succeeded</span><strong>{Number(mirrorReport.succeeded ?? 0)}</strong></div>
                    <div className="metric-card"><span>Skipped</span><strong>{Number(mirrorReport.skipped ?? 0)}</strong></div>
                    <div className="metric-card"><span>Failed</span><strong>{Number(mirrorReport.failed ?? 0)}</strong></div>
                  </div>
                  <p>Verified backup(s): {(mirrorReport.backups ?? []).join(", ") || "No backup was required."}</p>
                  <details><summary>Full execution report</summary><pre>{JSON.stringify(mirrorReport, null, 2)}</pre></details>
                </div>
              )}
              {stalePlan && <div className="error-notice stale-notice"><strong>Plan is stale</strong><p>One or both libraries changed after scanning. Rescan before building or executing another preview.</p><button className="secondary-button" onClick={() => void scan()}>Rescan libraries</button></div>}
              {error && <div className="error-notice" role="alert">{error}</div>}
            </>
          )}

          {active !== "library" && active !== "compare" && active !== "review" && active !== "mirror" && (
            <div className="empty-section"><div className="empty-icon" aria-hidden="true">{section.mark}</div><h2>{section.label} is waiting for its safety workflow</h2><p>{section.hint}. This section remains unavailable until review, freshness validation, verified backups, and recovery behavior are connected to the Python engine.</p><button className="secondary-button" onClick={() => setActive("library")}>Back to library workspace</button></div>
          )}

          {error && active === "library" && <div className="error-notice" role="alert">{error}</div>}
          <footer className="page-footer"><span><span className="status-dot" /> {scanning ? progress : executionReport ? `Last Safe execution: ${String(executionReport.final_status)}` : "Scan is read-only · no library files changed"}</span><span>Python stays the sync engine · Tauri stays the desktop shell</span></footer>
        </section>
      </main>
    </div>
  );
}
export default App;
