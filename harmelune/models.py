from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Side = Literal["a", "b", "laptop", "phone"]
_UNSET = object()


@dataclass(slots=True)
class FileState:
    relative_path: str
    size: int
    modified_ns: int
    file_hash: str | None = None


@dataclass(slots=True)
class Track:
    path: Path
    side: Side
    title: str = ""
    artist: str = ""
    album: str = ""
    duration: float | None = None
    size: int = 0
    modified_ns: int = 0
    file_hash: str | None = None
    artwork_hash: str | None = None
    artwork_hashes: tuple[str, ...] = ()

    @property
    def artwork_count(self) -> int:
        return len(self.artwork_hashes) or (1 if self.artwork_hash else 0)

    @property
    def display_title(self) -> str:
        return self.title or self.path.stem

    @property
    def display_artist(self) -> str:
        return self.artist or "Unknown artist"

    @property
    def display_album(self) -> str:
        return self.album or "Unknown album"


@dataclass(slots=True)
class Match:
    library_a: Track
    library_b: Track
    confidence: float
    metadata_conflict: bool = False
    artwork_conflict: bool = False
    confirmed: bool = True
    match_kind: str = "trusted"
    reasons: tuple[str, ...] = ()

    @property
    def laptop(self) -> Track:
        return self.library_a

    @property
    def phone(self) -> Track:
        return self.library_b


@dataclass(slots=True)
class ScanResult:
    side: Side
    root: Path
    tracks: list[Track] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    fingerprint: dict[str, FileState] = field(default_factory=dict)
    unsupported_audio_files: int = 0
    enumeration_complete: bool = True


@dataclass(slots=True, init=False)
class SyncPlan:
    library_a_only: list[Track] = field(default_factory=list)
    library_b_only: list[Track] = field(default_factory=list)
    matches: list[Match] = field(default_factory=list)
    library_a_root: Path | None = None
    library_b_root: Path | None = None
    fingerprint_a: dict[str, FileState] | None = None
    fingerprint_b: dict[str, FileState] | None = None

    def __init__(self, library_a_only=None, library_b_only=None, matches=None, library_a_root=None, library_b_root=None, fingerprint_a=_UNSET, fingerprint_b=_UNSET, *, laptop_only=None, phone_only=None):
        self.library_a_only = list(library_a_only if library_a_only is not None else (laptop_only or []))
        self.library_b_only = list(library_b_only if library_b_only is not None else (phone_only or []))
        self.matches = list(matches or [])
        self.library_a_root = library_a_root
        self.library_b_root = library_b_root
        self.fingerprint_a = None if fingerprint_a is _UNSET or fingerprint_a is None else dict(fingerprint_a)
        self.fingerprint_b = None if fingerprint_b is _UNSET or fingerprint_b is None else dict(fingerprint_b)

    @property
    def laptop_only(self) -> list[Track]:
        return self.library_a_only

    @property
    def phone_only(self) -> list[Track]:
        return self.library_b_only


class SyncMode:
    SAFE = "safe"
    MIRROR = "mirror"
    RECONCILE = "reconcile"
