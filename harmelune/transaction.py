from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .backup import MANIFEST_NAME, BackupVerificationError, verify_backup, verify_backup_contents


class OperationKind(str, Enum):
    COPY = "copy"
    REPLACE = "replace"
    DELETE = "delete"


@dataclass(frozen=True, slots=True)
class FileOperation:
    kind: OperationKind
    source: Path | None
    destination: Path


@dataclass(slots=True)
class TransactionResult:
    attempted: int = 0
    succeeded: list[FileOperation] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    rolled_back: bool = False
    rollback_failures: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if not self.failures:
            return "SUCCESS"
        if self.rolled_back and not self.rollback_failures:
            return "FAILED"
        return "PARTIAL"


def _library_for(path: Path, backups: dict[Path, Path]) -> Path:
    resolved = path.resolve()
    candidates = [root.resolve() for root in backups if resolved.is_relative_to(root.resolve())]
    if not candidates:
        raise ValueError(f"No transaction backup covers destination: {path}")
    return max(candidates, key=lambda root: len(root.parts))


def _restore_from_backup(library: Path, backup: Path) -> None:
    """Restore a verified backup and verify the resulting library."""
    library = library.resolve()
    backup = backup.resolve()
    if library == backup or library.is_relative_to(backup) or backup.is_relative_to(library):
        raise ValueError("Rollback backup overlaps the library.")
    verify_backup_contents(backup)

    # Stage a complete copy before touching the live library. This reduces (but cannot
    # eliminate) the risk of a partial restore if the filesystem fails mid-replacement.
    staging = Path(tempfile.mkdtemp(prefix=f".{library.name}.harmelune-rollback-", dir=library.parent))
    try:
        for child in backup.iterdir():
            if child.name == MANIFEST_NAME:
                continue
            destination = staging / child.name
            if child.is_dir():
                shutil.copytree(child, destination)
            else:
                shutil.copy2(child, destination)

        for child in library.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        for child in staging.iterdir():
            destination = library / child.name
            if child.is_dir():
                shutil.copytree(child, destination)
            else:
                shutil.copy2(child, destination)
        verify_backup(library, backup)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def execute_transaction(
    operations: list[FileOperation],
    backups: dict[Path, Path],
) -> TransactionResult:
    """Execute operations and report explicit recovery guidance if rollback is incomplete."""
    result = TransactionResult()
    if not operations:
        return result

    affected = {_library_for(operation.destination, backups) for operation in operations}
    for library in affected:
        verify_backup(library, backups[library])

    for operation in operations:
        result.attempted += 1
        try:
            if operation.kind is OperationKind.DELETE:
                operation.destination.unlink()
            elif operation.kind in {OperationKind.COPY, OperationKind.REPLACE}:
                if operation.source is None:
                    raise ValueError(f"{operation.kind.value} operation has no source: {operation.destination}")
                operation.destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(operation.source, operation.destination)
            else:
                raise ValueError(f"Unknown operation kind: {operation.kind}")
            result.succeeded.append(operation)
        except (OSError, ValueError) as exc:
            result.failures.append(f"Operation {operation.kind.value} failed for {operation.destination}: {exc}")
            break

    if not result.failures:
        return result

    rollback_errors: list[str] = []
    for library in sorted(affected, key=lambda item: str(item).casefold()):
        backup = backups[library]
        try:
            _restore_from_backup(library, backup)
        except (OSError, ValueError, BackupVerificationError) as exc:
            rollback_errors.append(
                f"MANUAL RECOVERY REQUIRED for {library}: rollback failed ({exc}). "
                f"Preserve the library and restore from the verified backup at {backup}."
            )
    result.rollback_failures.extend(rollback_errors)
    result.rolled_back = not rollback_errors
    return result
