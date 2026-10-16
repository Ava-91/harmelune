# Manual UI verification checklist

Automated tests cover core logic and selected keyboard behavior, but they cannot prove usability on every Windows display or assistive-technology setup. Run this checklist on Windows before a release.

- [ ] Windows display scaling at 100%, 125%, 150%, and 200%: no clipped primary actions or inaccessible dialogs.
- [ ] Small display / low vertical resolution: resize the main window and each dialog; confirm tables and actions remain reachable.
- [ ] Long paths and Unicode folder names: select folders with long nested paths and non-Latin characters; verify readable wrapping and scrolling.
- [ ] Keyboard-only navigation: Tab / Shift+Tab through controls; F5 starts comparison; Ctrl+P opens preview when allowed; Ctrl+H opens health; Enter opens selected result details; Escape closes dialogs or cancels a scan.
- [ ] Screen reader: verify names, roles, state, and table headings are announced by Narrator or the screen reader in use. This remains a manual compatibility check.
- [ ] Scan interruption: cancel a scan on a large folder; confirm the scan is reported incomplete and Preview / Apply stay disabled until a clean rescan.
- [ ] Failure recovery: use disposable test libraries and simulated I/O failures; confirm rollback failure clearly shows the backup path and manual recovery warning.
- [ ] Backup messaging: confirm the UI says the manifest check verifies integrity against a stored manifest, not authenticity of who created it.
- [ ] Never use a real music library for destructive failure-injection tests.
