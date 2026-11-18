# Desktop migration and stabilization audit

## Architecture

- Legacy Tkinter entry point: `app.py`; shared orchestration: `harmelune/services.py`.
- JSON Lines protocol: `harmelune/sidecar.py` (v1).
- React/TypeScript/Vite UI: `desktop/`; Tauri v2/Rust shell: `desktop/src-tauri/`.
- Windows bundle target: NSIS with `binaries/harmelune-sidecar.exe`.
- Python remains authoritative for matching, path safety, previews, backups, restore, and transactions.

The sidecar exposes scan/listing, Safe/Reconcile/Mirror/Restore previews and gated execution. It is not merely read-only.

## Phase 1 — stabilization

### Updated here
- Corrected this audit to describe the real command surface and execution gates.
- Corrected the desktop banner: Mirror and Restore are available behind explicit safety gates, not locked.
- Added Health and History protocol endpoints and desktop views (see Phase 2).

### Remaining gaps
- **Nightly integrity:** workflow runs on Ubuntu and Windows and now uses PowerShell-safe folded pytest syntax. Confirm a post-fix Actions run passes both legs; code inspection is not test evidence.
- **Timeout/cancellation:** Rust currently performs synchronous stdout reads while holding the engine mutex. A hung sidecar can block a request; no user cancellation command reaches the Python scanner's existing cancellation callback. Follow-up: dedicated reader thread, bounded line size, deadlines, cancellation propagation, and child termination/reaping with plan invalidation. Cancellation is not claimed implemented.
- **npm lockfile:** `desktop/package-lock.json` is absent and CI runs `npm install`. Generate it with npm using the supported Node version, commit it, then switch CI to `npm ci`. Do not guess transitive versions or integrity hashes.
- **Packaging:** build/check workflows do not prove clean-machine NSIS installation or end-to-end operation.

## Phase 2 — desktop completion

### Sync History
The UI calls `history` and renders successful Safe, Reconcile, Mirror, and Restore reports newest-first with timestamps, statuses, counts, and full report details. **Limitation:** history is sidecar-session scoped, capped at 100, and lost when the process exits. It is not a durable audit log; persistent/exportable history remains future work.

### Library Health
The UI calls `health` for the current scan and displays per-library track count, metadata completeness, artwork coverage, duplicate tracks/groups, scan errors, unsupported audio-like files, and unresolved conflicts/fuzzy matches. The sidecar delegates to `harmelune.health.build_health_report`; no frontend file analysis is duplicated. Health requires an active in-memory scan plan.

### Navigation and states
History and Health have dedicated loading, empty, and error states rather than the generic migration placeholder. The banner now reflects the implemented modes.

## Safety invariants
- Both roots must be valid, separate, and non-overlapping.
- Scan/preview are read-only; incomplete scans cannot be applied.
- Fuzzy matches/conflicts require explicit review; plans are revalidated for freshness.
- Verified backups stay outside protected libraries.
- Safe is copy-only; Reconcile never deletes.
- Mirror may delete/replace and requires exact `MIRROR`; Restore requires verified backup, exact target identity, safety backup, and exact `RESTORE`.
- Interrupted transactions must not auto-resume.
- Destructive tests use temporary/synthetic/disposable libraries only.

## Verification checklist
- [ ] `python -m pytest -q` on Windows and Ubuntu.
- [ ] Confirm Nightly integrity succeeds on both matrix legs after the PowerShell fix.
- [ ] Generate/commit `desktop/package-lock.json`, then run `npm ci` and `npm run build`.
- [ ] Run `cargo check --manifest-path desktop/src-tauri/Cargo.toml`.
- [ ] Add protocol tests for Health/History, stale plans, empty history, and the 100-entry cap.
- [ ] Exercise both sections in the actual Tauri app on Windows.
- [ ] Complete `docs/manual-ui-qa.md`; install/smoke-test NSIS on clean Windows with disposable libraries.

Automated CI/source review do not establish clean-machine installer correctness or manual accessibility/usability.
