# Getting started

> **Goal:** go from a fresh Windows checkout to a safe first dry run without changing your music library.

Harmelune compares two independent music folders, builds a reviewable synchronization plan, and lets you inspect that plan before applying changes.

## Before you begin

You need:

- Windows 10 or Windows 11 for the supported packaged workflow
- Two accessible music folders
- A separate location for backups
- Either Python 3.11+ or a packaged `harmelune.exe`

### Choose your two libraries

Think of the folders as:

- **Library A** — your first collection
- **Library B** — your second collection

They can be folders on the same computer, different drives, removable storage, exports, or independently maintained copies.

They must be:

- existing directories
- readable and accessible
- different from each other
- not nested inside one another

Your backup location must also be outside both libraries.

## Option 1 — Run from source

Open PowerShell in the repository:

```powershell
python -m pip install -r requirements.txt
python app.py
```

For development and testing, also install:

```powershell
python -m pip install -r requirements-dev.txt
```

The repository includes `install.bat` and `run.bat` for Windows source checkouts.

## Option 2 — Run the Windows executable

Harmelune can be packaged as a standalone `harmelune.exe`.

If you have a Windows build artifact, place the executable in a convenient folder and launch it normally. The executable does not require a separate Python installation.

The automated Windows build checks that:

1. the executable is produced
2. its version metadata is present
3. the packaged process starts and remains running briefly

Those checks do not replace interactive testing of the complete GUI.

## First launch

If Harmelune has no initialized settings, the setup wizard opens.

Follow the steps in order:

### 1. Select Library A

Choose your first music folder.

### 2. Select Library B

Choose the second music folder.

Harmelune rejects identical and nested library paths before setup can continue.

### 3. Choose the master

Select which library is the authoritative source when a directed operation needs one.

This is an explicit choice; Harmelune does not assume that one folder is always the source.

### 4. Choose a synchronization mode

| Mode | Use it when |
| --- | --- |
| **Safe** | You want a conservative synchronization path without trusting unconfirmed fuzzy matches |
| **Reconcile** | You want to explicitly decide how conflicts and uncertain matches should be handled |
| **Mirror** | You intentionally want a master-direction mirror operation and understand its consequences |

For a first run, start with **Safe** or **Reconcile** and inspect the resulting plan before considering any more aggressive operation.

### 5. Choose a backup location

Select a directory outside both music libraries.

Modifying operations create and verify backups before changing affected libraries.

### 6. Finish setup

The wizard validates the configuration and saves it. It does not scan, copy, delete, or synchronize your music while you are completing setup.

## Your first dry run

Once setup is complete:

1. Start a scan of both libraries.
2. Wait for scanning to finish.
3. Review matched tracks, library-only tracks, conflicts, and fuzzy matches.
4. Use the results search field to find a title, artist, category, or displayed path. Search only changes which rows are visible; it does not alter match decisions or the synchronization plan.
5. Use the sort menu to order results by category or track details. The category buttons continue to filter the result set, and the summary shows visible counts plus uncertain matches and conflict decisions still needing review.
6. Inspect the proposed operations.
7. Run a **dry run**.
8. Read the resulting plan before applying anything.

A dry run is a preview. It is not a backup and it does not replace reviewing important changes.

### What to look for

Pay particular attention to:

- fuzzy matches marked for review
- metadata conflicts
- artwork conflicts
- tracks that exist in only one library
- unreadable files or scan errors
- unexpected source/destination directions

If a match looks wrong, do not treat the plan as ready. Review the evidence and choose an explicit decision where the workflow requires one.

## After the dry run

If the plan looks correct:

1. keep an independent backup of anything important
2. confirm the configured backup location is separate from both libraries
3. use the appropriate synchronization mode
4. review the execution result
5. inspect the execution report and health information

If a restore or another state-changing operation invalidates the plan, scan both libraries again before applying another synchronization.

## If something goes wrong

Start with the relevant guide:

- [Synchronization workflow](synchronization-workflow.md)
- [Matching and match explanations](matching.md)
- [Safety, backups, and recovery](safety-and-recovery.md)
- [Troubleshooting and FAQ](troubleshooting.md)

For a bug report, include the Harmelune version, operating system, relevant error text, and a description of the two library/backup setup without sharing private music files or credentials.
