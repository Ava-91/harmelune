# Desktop migration audit (2026-10-16)

## Scope and repository state

This audit was performed against the current `main` tree, not an earlier conversation snapshot.

- Repository: `Ava-91/harmelune`
- Audited `main` commit: `e005c5e552995080b51274e042ed04ee33822610`
- Default branch: `main`
- Open pull requests at audit time: none
- Open issues at audit time: none
- Existing migration PRs: #153 (Python services), #154 (Tauri/React shell), and #155 (read-only sidecar) are merged.

This commit already contains Phase 1 and Phase 2 work. This document records the verified baseline and remaining risks; it does not replace the legacy app or enable desktop-side file mutations.

## Actual dependencies and packaging

### Python

- Runtime: `requirements.txt` includes Mutagen (`>=1.48.1,<2`) and Pillow (`>=12.3.0,<13`).
- Development/build: `requirements-dev.txt` adds pytest (`>=9.1.1,<10`) and PyInstaller (`>=6.22.3,<7`).
- Existing app entry point: `app.py` (Tkinter).
- Shared orchestration: `harmelune/services.py`.
- Read-only protocol process: `harmelune/sidecar.py`.
- Sidecar spec: `harmelune-sidecar.spec`; legacy app spec remains `harmelune.spec`.

### Desktop

- Frontend: React 19, TypeScript 5.9, Vite 6, Tauri API/plugin v2.
- Rust shell: Tauri v2 and `serde_json`.
- Config: `desktop/src-tauri/tauri.conf.json`; only the dialog-open plugin is installed, and the default capability grants `core:default` and `dialog:allow-open`.
- The bundle currently targets Windows NSIS and expects `binaries/harmelune-sidecar.exe`.
- No npm lockfile is present in the current tree. The desktop workflow runs `npm install`, so dependency resolution is not fully reproducible yet.

## Current architecture and phase status

### Phase 1 — Python service layer

`harmelune/services.py` exposes `scan_libraries`, `preview_workflow`, and `execute_workflow`. Current `app.py` calls these services for scan, preview, and Safe/Reconcile/Mirror execution while retaining the Tkinter window, dialogs, and worker/UI-thread handling.

Regression coverage includes `tests/test_services.py`, `tests/test_settings.py`, and the existing scan, review, freshness, path-safety, backup, transaction, recovery, and mode-specific test modules. Synthetic WAV fixtures and temporary directories are used by the service tests.

### Phase 2 — Tauri v2 + React/TypeScript shell

The `desktop/` project contains the React UI, TypeScript/Vite configuration, Rust shell, Tauri configuration, and restricted capability file. It is separate from `app.py`; the Tkinter entry point and its existing packaging are retained.

### Phase 3 — read-only sidecar baseline

The current Python protocol is version 1 and uses JSON Lines. The sidecar exposes only `hello`, `scan`, `list_tracks`, and `shutdown`. It does not expose execution, arbitrary shell commands, or arbitrary Python evaluation. The Rust bridge starts the sidecar as a child process, uses stdin/stdout pipes, forwards progress events, and attempts clean shutdown on application exit.

This is a read-only integration baseline, not a completed migration of review, preview, or apply operations.

## Safety invariants to preserve

The existing safety-critical engine remains in Python. The desktop work must continue to use its established functions rather than reimplementing filesystem decisions in Rust or TypeScript.

- Validate that both library roots exist, are directories, and are separate/non-overlapping.
- Keep scanning and dry-run preview read-only; incomplete/error scans must not be treated as safe-to-apply.
- Keep fuzzy matches and conflicts unconfirmed until explicit user review.
- Revalidate plan freshness before applying; stale plans must be rejected and rescanned.
- Require verified backups before mutations and reject backup paths that overlap protected libraries.
- Safe mode must not delete or overwrite destination files.
- Reconcile must apply only explicit decisions and must not delete files.
- Mirror remains the last mode to migrate because it can replace/delete destination files and requires the exact `MIRROR` confirmation.
- Restore must require a verified backup, exact `RESTORE` confirmation, a safety backup of the target, and recovery/verification handling.
- Never automatically resume an interrupted transaction; show recovery warnings and inspect journals/backups.
- Test using temporary directories and synthetic audio fixtures or disposable copies only, never a user's only originals.

## Verification observed

The following GitHub Actions runs were inspected on 2026-10-16:

- Main-branch tests: [run 38934666913](https://github.com/Ava-91/harmelune/actions/runs/38934666913) — completed successfully.
- Main-branch desktop workflow: [run 38934667009](https://github.com/Ava-91/harmelune/actions/runs/38934667009) — completed successfully.
- Phase 1 PR checks: [tests](https://github.com/Ava-91/harmelune/actions/runs/38934652550), [desktop workflow](https://github.com/Ava-91/harmelune/actions/runs/38934652705), and [Windows build](https://github.com/Ava-91/harmelune/actions/runs/38934652497) — completed successfully.
- Phase 2 PR checks: [tests](https://github.com/Ava-91/harmelune/actions/runs/38934622136), [desktop workflow](https://github.com/Ava-91/harmelune/actions/runs/38934622129), and [Windows build](https://github.com/Ava-91/harmelune/actions/runs/38934622142) — completed successfully.

These are hosted CI results. No local Python, npm, or Cargo commands were executed as part of this audit, and these results do not prove manual testing on a clean Windows machine with a real user library.

## Risks and next steps

1. **Dependency reproducibility:** add and commit a desktop lockfile, then use `npm ci` in CI.
2. **Protocol hardening:** add bounded response-line handling and an explicit timeout/cancellation strategy for stalled child processes. Keep stdout reserved for JSONL and diagnostics on stderr.
3. **Progress/cancellation UX:** the protocol can report scan progress, but cancellation of an in-flight scan is not yet a desktop workflow.
4. **UI/backend contract:** add protocol-level schema/contract tests for every exposed command before adding new commands.
5. **Phase 4 review and preview:** migrate decisions and dry-run display first; keep apply unavailable until the backend protocol can represent a reviewed plan, blockers, backup verification, and stale-plan errors.
6. **Execution migration:** enable Safe first, then Reconcile; migrate Mirror last with exact confirmation. Keep the Tkinter app usable throughout.
7. **Packaging validation:** verify the packaged sidecar resource path and NSIS installer on a clean Windows environment. CI compile/package checks are not a substitute for an end-to-end install and disposable-library smoke test.

No safety-critical behavior should be duplicated in the frontend. Python remains the authoritative music-processing and synchronization engine.
