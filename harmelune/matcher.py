from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from .models import FileState, Match, ScanResult, SyncPlan, Track


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).casefold()
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def track_key(track: Track) -> tuple[str, str, str]:
    return normalize(track.artist), normalize(track.title or track.path.stem), normalize(track.album)


def _same_duration(a: Track, b: Track, tolerance: float = 2.0) -> bool:
    return a.duration is not None and b.duration is not None and abs(a.duration - b.duration) <= tolerance


_VARIANT_PATTERNS = {
    "live": r"\blive\b|\blive at\b|\blive version\b",
    "remix": r"\bremix\b|\bremixed\b|\bextended mix\b",
    "acoustic": r"\bacoustic\b|\bunplugged\b",
    "instrumental": r"\binstrumental\b|\bkaraoke\b",
    "demo": r"\bdemo\b|\bdemonstration\b",
    "clean": r"\bclean version\b|\bradio edit\b|\bradio version\b",
    "explicit": r"\bexplicit version\b|\bexplicit\b",
    "sped_up": r"\bsped up\b|\bspeed up\b|\bnightcore\b",
    "slowed": r"\bslowed\b|\bslowed down\b|\bslowed reverb\b",
    "orchestral": r"\borchestral\b|\bsymphonic\b",
    "re_recorded": r"\bre recorded\b|\bre recorded version\b",
}


def _variant_tags(track: Track) -> frozenset[str]:
    text = normalize(f"{track.display_title} {track.path.stem}")
    return frozenset(tag for tag, pattern in _VARIANT_PATTERNS.items() if re.search(pattern, text))


def _compatible_versions(a: Track, b: Track) -> bool:
    """Do not auto-match tracks when only one side identifies a materially different version."""
    return _variant_tags(a) == _variant_tags(b)


def _fuzzy_eligible(a: Track, b: Track) -> bool:
    if not _compatible_versions(a, b):
        return False
    title_score, _name_score, artist_score, _album_score, _duration_score = _similarity_parts(a, b)
    if title_score < 0.82:
        return False
    if a.artist and b.artist and artist_score < 0.80:
        return False
    # When both durations exist, large differences usually indicate a different version.
    if a.duration is not None and b.duration is not None and abs(a.duration - b.duration) > 3.0:
        return False
    return True


def _artwork_values(track: Track) -> tuple[str, ...]:
    return track.artwork_hashes or ((track.artwork_hash,) if track.artwork_hash else ())


def _artwork_conflict(a: Track, b: Track) -> bool:
    left, right = _artwork_values(a), _artwork_values(b)
    return left != right and bool(left or right)


def _metadata_conflict(a: Track, b: Track) -> bool:
    fields = ((a.title, b.title), (a.artist, b.artist), (a.album, b.album))
    return any(x and y and normalize(x) != normalize(y) for x, y in fields)


def _similarity_parts(a: Track, b: Track) -> tuple[float, float, float, float, float]:
    title_score = SequenceMatcher(None, normalize(a.display_title), normalize(b.display_title)).ratio()
    name_score = SequenceMatcher(None, normalize(a.path.stem), normalize(b.path.stem)).ratio()
    artist_score = SequenceMatcher(None, normalize(a.artist), normalize(b.artist)).ratio() if a.artist or b.artist else 1.0
    album_score = SequenceMatcher(None, normalize(a.album), normalize(b.album)).ratio() if a.album or b.album else 1.0
    duration_score = 1.0 if _same_duration(a, b) else 0.0
    return title_score, name_score, artist_score, album_score, duration_score


def similarity(a: Track, b: Track) -> float:
    title_score, name_score, artist_score, album_score, duration_score = _similarity_parts(a, b)
    return 0.45 * title_score + 0.15 * name_score + 0.20 * artist_score + 0.10 * album_score + 0.10 * duration_score


def _metadata_reasons() -> tuple[str, ...]:
    return ("Normalized metadata key matches (artist, title/filename, album)",)


def _filename_reasons(a: Track, b: Track) -> tuple[str, ...]:
    reasons = ["Filename stem matches after normalization"]
    delta = abs(a.duration - b.duration) if a.duration is not None and b.duration is not None else None
    if delta is not None and delta <= 2.0:
        reasons.append(f"Duration within 2.0s tolerance (difference: {delta:.2f}s)")
    if normalize(a.artist) == normalize(b.artist):
        reasons.append("Artist key matches after normalization")
    return tuple(reasons)


def _fuzzy_reasons(a: Track, b: Track, confidence: float) -> tuple[str, ...]:
    title_score, name_score, artist_score, album_score, _duration_score = _similarity_parts(a, b)
    reasons = [
        f"Heuristic similarity score (not a probability): {confidence:.0%}",
        f"Title similarity: {title_score:.0%}",
        f"Filename similarity: {name_score:.0%}",
        f"Artist similarity: {artist_score:.0%}",
        f"Album similarity: {album_score:.0%}",
    ]
    if a.duration is not None and b.duration is not None:
        delta = abs(a.duration - b.duration)
        if delta <= 2.0:
            reasons.append(f"Duration within 2.0s tolerance (difference: {delta:.2f}s)")
        else:
            reasons.append(f"Duration difference: {delta:.2f}s")
    else:
        reasons.append("Duration unavailable (no duration contribution)")
    return tuple(reasons)


def _observed_reasons(a: Track, b: Track) -> tuple[str, ...]:
    if a.file_hash and b.file_hash and a.file_hash == b.file_hash:
        return ("Byte-identical SHA-256",)
    title_score = SequenceMatcher(None, normalize(a.display_title), normalize(b.display_title)).ratio()
    artist_score = SequenceMatcher(None, normalize(a.artist), normalize(b.artist)).ratio() if a.artist or b.artist else 1.0
    reasons = [f"Title similarity: {title_score:.0%}", f"Artist similarity: {artist_score:.0%}"]
    if a.duration is not None and b.duration is not None:
        reasons.append(f"Duration difference: {abs(a.duration - b.duration):.2f}s")
    name_score = SequenceMatcher(None, normalize(a.path.stem), normalize(b.path.stem)).ratio()
    if name_score >= 0.8:
        reasons.append(f"Filename similarity: {name_score:.0%}")
    return tuple(reasons)


def _match_reasons(a: Track, b: Track, kind: str, confidence: float) -> tuple[str, ...]:
    if kind == "hash" and a.file_hash and b.file_hash and a.file_hash == b.file_hash:
        return ("Byte-identical SHA-256",)
    if kind == "metadata" and track_key(a) == track_key(b):
        return _metadata_reasons()
    if kind == "filename" and normalize(a.path.stem) == normalize(b.path.stem) and (_same_duration(a, b) or normalize(a.artist) == normalize(b.artist)):
        return _filename_reasons(a, b)
    if kind == "fuzzy":
        return _fuzzy_reasons(a, b, confidence)
    return _observed_reasons(a, b)


def _make_match(a: Track, b: Track, confidence: float, confirmed: bool, kind: str) -> Match:
    return Match(
        a,
        b,
        confidence,
        metadata_conflict=_metadata_conflict(a, b),
        artwork_conflict=_artwork_conflict(a, b),
        confirmed=confirmed,
        match_kind=kind,
        reasons=_match_reasons(a, b, kind, confidence),
    )


def _relative_track_path(track: Track, root) -> str:
    """Return a stable fingerprint key for both scanned and synthetic test tracks."""
    if track.path.is_absolute():
        return str(track.path.resolve().relative_to(root.resolve()))
    return str(track.path)


def _fingerprint(result: ScanResult) -> dict[str, FileState]:
    data: dict[str, FileState] = {}
    for track in result.tracks:
        relative = _relative_track_path(track, result.root)
        data[relative] = FileState(relative, track.size, track.modified_ns, track.file_hash)
    return data


def build_plan(a: ScanResult, b: ScanResult, threshold: float = 0.88) -> SyncPlan:
    """Build a conservative, library-agnostic reconciliation plan."""
    plan = SyncPlan(
        library_a_root=a.root.resolve(),
        library_b_root=b.root.resolve(),
        fingerprint_a=_fingerprint(a),
        fingerprint_b=_fingerprint(b),
    )
    used_b: set[int] = set()
    matched_a: set[object] = set()
    by_hash: dict[str, list[tuple[int, Track]]] = {}
    for i, track in enumerate(b.tracks):
        if track.file_hash:
            by_hash.setdefault(track.file_hash, []).append((i, track))
    for a_track in a.tracks:
        candidates = [x for x in by_hash.get(a_track.file_hash or "", []) if x[0] not in used_b]
        if a_track.file_hash and len(candidates) == 1:
            i, b_track = candidates[0]
            used_b.add(i)
            matched_a.add(a_track.path)
            plan.matches.append(_make_match(a_track, b_track, 1.0, True, "hash"))
    by_key: dict[tuple[str, str, str], list[tuple[int, Track]]] = {}
    for i, track in enumerate(b.tracks):
        if i not in used_b:
            by_key.setdefault(track_key(track), []).append((i, track))
    for a_track in a.tracks:
        if a_track.path in matched_a:
            continue
        candidates = [x for x in by_key.get(track_key(a_track), []) if x[0] not in used_b and _compatible_versions(a_track, x[1])]
        if len(candidates) == 1:
            i, b_track = candidates[0]
            used_b.add(i)
            matched_a.add(a_track.path)
            plan.matches.append(_make_match(a_track, b_track, 1.0, True, "metadata"))
    by_name: dict[str, list[tuple[int, Track]]] = {}
    for i, track in enumerate(b.tracks):
        if i not in used_b:
            by_name.setdefault(normalize(track.path.stem), []).append((i, track))
    for a_track in a.tracks:
        if a_track.path in matched_a:
            continue
        candidates = [
            x
            for x in by_name.get(normalize(a_track.path.stem), [])
            if x[0] not in used_b and _compatible_versions(a_track, x[1]) and (_same_duration(a_track, x[1]) or normalize(a_track.artist) == normalize(x[1].artist))
        ]
        if len(candidates) == 1:
            i, b_track = candidates[0]
            used_b.add(i)
            matched_a.add(a_track.path)
            plan.matches.append(_make_match(a_track, b_track, 0.98, True, "filename"))
    remaining = [(i, t) for i, t in enumerate(b.tracks) if i not in used_b]
    for a_track in a.tracks:
        if a_track.path in matched_a:
            continue
        ranked = sorted(((similarity(a_track, t), i, t) for i, t in remaining if _fuzzy_eligible(a_track, t)), reverse=True, key=lambda x: x[0])
        if ranked and ranked[0][0] >= threshold and (len(ranked) == 1 or ranked[0][0] - ranked[1][0] >= 0.06):
            score, i, b_track = ranked[0]
            used_b.add(i)
            matched_a.add(a_track.path)
            remaining = [(j, t) for j, t in remaining if j != i]
            plan.matches.append(_make_match(a_track, b_track, score, False, "fuzzy"))
        else:
            plan.library_a_only.append(a_track)
    plan.library_b_only = [t for i, t in enumerate(b.tracks) if i not in used_b]
    return plan
