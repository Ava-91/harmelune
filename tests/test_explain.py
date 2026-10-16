from pathlib import Path

from harmelune.explain import explain_match
from harmelune.matcher import build_plan
from harmelune.models import Match, ScanResult, Track


def test_exact_hash_is_explained():
    left = Track(path=Path("a.mp3"), side="a", title="Song", file_hash="abc")
    right = Track(path=Path("b.mp3"), side="b", title="Song", file_hash="abc")
    explanation = explain_match(Match(left, right, 1.0, confirmed=True))
    assert explanation.identity == "Exact match"
    assert "Byte-identical SHA-256" in explanation.reasons


def test_metadata_and_artwork_conflicts_are_explained():
    left = Track(path=Path("a.mp3"), side="a", title="New", artist="Artist", artwork_hashes=("a",))
    right = Track(path=Path("b.mp3"), side="b", title="Old", artist="Artist", artwork_hashes=("b",))
    explanation = explain_match(Match(left, right, 0.9, confirmed=True))
    assert "Title differs" in explanation.conflicts
    assert "Embedded artwork differs" in explanation.conflicts


def test_missing_artwork_uses_library_a_b_labels():
    left = Track(path=Path("a.mp3"), side="a", title="Song", artwork_hashes=("hash1",))
    right = Track(path=Path("b.mp3"), side="b", title="Song")
    explanation = explain_match(Match(left, right, 0.9, confirmed=True))
    assert "Library B is missing embedded artwork" in explanation.conflicts
    assert "Laptop" not in " ".join(explanation.conflicts)
    assert "Phone" not in " ".join(explanation.conflicts)

    left2 = Track(path=Path("a2.mp3"), side="a", title="Song")
    right2 = Track(path=Path("b2.mp3"), side="b", title="Song", artwork_hashes=("hash2",))
    explanation2 = explain_match(Match(left2, right2, 0.9, confirmed=True))
    assert "Library A is missing embedded artwork" in explanation2.conflicts


def test_artwork_hash_fallback_matches_matcher_representation():
    """explain must use the same artwork_hash fallback the matcher uses."""
    left = Track(path=Path("a.mp3"), side="a", title="Song", artwork_hash="legacy-hash")
    right = Track(path=Path("b.mp3"), side="b", title="Song", artwork_hash="other-hash")
    explanation = explain_match(Match(left, right, 0.9, confirmed=True))
    assert "Embedded artwork differs" in explanation.conflicts


def test_hash_match_explanation_reports_content_identity_only():
    left = Track(
        Path("left.mp3"), "a", title="Left title", artist="Left artist", album="Left album",
        duration=200.0, file_hash="same-content", artwork_hashes=("left-art",),
    )
    right = Track(
        Path("renamed.mp3"), "b", title="Right title", artist="Right artist", album="Right album",
        duration=205.0, file_hash="same-content", artwork_hashes=("right-art",),
    )

    plan = build_plan(ScanResult("a", Path("A"), [left]), ScanResult("b", Path("B"), [right]))
    match = plan.matches[0]
    explanation = explain_match(match)

    assert match.match_kind == "hash"
    assert explanation.reasons == ("Byte-identical SHA-256",)
    assert not any("similarity" in reason.lower() for reason in explanation.reasons)
    assert "Title differs" in explanation.conflicts
    assert "Embedded artwork differs" in explanation.conflicts


def test_ambiguous_content_identity_does_not_claim_hash_was_decisive():
    left = Track(Path("song.mp3"), "a", title="Song", artist="Artist", album="Album", file_hash="duplicate-content")
    right = Track(Path("right.mp3"), "b", title="Song", artist="Artist", album="Album", file_hash="duplicate-content")
    other = Track(Path("other.mp3"), "b", title="Other", artist="Artist", album="Album", file_hash="duplicate-content")

    plan = build_plan(ScanResult("a", Path("A"), [left]), ScanResult("b", Path("B"), [right, other]))
    explanation = explain_match(plan.matches[0])

    assert plan.matches[0].match_kind == "metadata"
    assert "Byte-identical SHA-256" not in explanation.reasons
    assert explanation.reasons[0] == "Normalized metadata key matches (artist, title/filename, album)"


def test_metadata_match_explanation_does_not_claim_unused_similarity_signals():
    left = Track(Path("left.mp3"), "a", title="Song", artist="Artist", album="Album", duration=200.0, file_hash="left")
    right = Track(Path("right.mp3"), "b", title="song", artist="artist", album="album", duration=200.0, file_hash="right")

    plan = build_plan(ScanResult("a", Path("A"), [left]), ScanResult("b", Path("B"), [right]))
    explanation = explain_match(plan.matches[0])

    assert plan.matches[0].match_kind == "metadata"
    assert "Normalized metadata key matches" in explanation.reasons[0]
    assert not any(reason.startswith("Title similarity") for reason in explanation.reasons)
    assert not any(reason.startswith("Duration difference") for reason in explanation.reasons)
    assert explanation.identity == "Confirmed metadata match"


def test_filename_match_explanation_reports_duration_only_when_it_qualifies():
    left = Track(Path("song.mp3"), "a", title="Left title", artist="Left artist", album="Left album", duration=200.0, file_hash="left")
    right = Track(Path("song.mp3"), "b", title="Right title", artist="Right artist", album="Right album", duration=201.0, file_hash="right")

    plan = build_plan(ScanResult("a", Path("A"), [left]), ScanResult("b", Path("B"), [right]))
    explanation = explain_match(plan.matches[0])

    assert plan.matches[0].match_kind == "filename"
    assert explanation.reasons[0] == "Filename stem matches after normalization"
    assert "Duration within 2.0s tolerance (difference: 1.00s)" in explanation.reasons
    assert not any("Artist key matches" in reason for reason in explanation.reasons)
    assert not any("Title similarity" in reason for reason in explanation.reasons)
    assert explanation.identity == "Confirmed filename match"


def test_filename_match_explanation_reports_artist_when_duration_does_not_qualify():
    left = Track(Path("song.mp3"), "a", title="Left title", artist="Artist", album="Left album", duration=200.0, file_hash="left")
    right = Track(Path("song.mp3"), "b", title="Right title", artist="Artist", album="Right album", duration=205.0, file_hash="right")

    plan = build_plan(ScanResult("a", Path("A"), [left]), ScanResult("b", Path("B"), [right]))
    explanation = explain_match(plan.matches[0])

    assert "Filename stem matches after normalization" in explanation.reasons
    assert "Artist key matches after normalization" in explanation.reasons
    assert not any("Duration" in reason for reason in explanation.reasons)


def test_fuzzy_match_explanation_includes_every_scoring_component():
    left = Track(Path("song.mp3"), "a", title="Song", artist="Artist", album="Album One", duration=200.0, file_hash="left")
    right = Track(Path("song-copy.mp3"), "b", title="Song", artist="Artist", album="Album Two", duration=200.0, file_hash="right")

    plan = build_plan(ScanResult("a", Path("A"), [left]), ScanResult("b", Path("B"), [right]))
    match = plan.matches[0]
    explanation = explain_match(match)

    assert match.match_kind == "fuzzy"
    assert match.confirmed is False
    assert explanation.identity == "Fuzzy match — review required"
    for reason in (
        "Heuristic similarity score (not a probability):",
        "Title similarity:",
        "Filename similarity:",
        "Artist similarity:",
        "Album similarity:",
        "Duration within 2.0s tolerance",
    ):
        assert any(reason in value for value in explanation.reasons)
    assert not any("Filename stem matches" in value for value in explanation.reasons)


def test_full_artwork_identity_takes_precedence_over_legacy_primary_hash():
    left = Track(Path("a.mp3"), "a", title="Song", artist="Artist", album="Album", artwork_hash="legacy-a", artwork_hashes=("same-art",))
    right = Track(Path("b.mp3"), "b", title="Song", artist="Artist", album="Album", artwork_hash="legacy-b", artwork_hashes=("same-art",))

    explanation = explain_match(Match(left, right, 1.0, confirmed=True, match_kind="metadata"))

    assert "Embedded artwork differs" not in explanation.conflicts


def test_multi_artwork_order_conflict_is_explained():
    left = Track(Path("a.mp3"), "a", title="Song", artist="Artist", album="Album", artwork_hashes=("first", "second"))
    right = Track(Path("b.mp3"), "b", title="Song", artist="Artist", album="Album", artwork_hashes=("second", "first"))

    explanation = explain_match(Match(left, right, 1.0, confirmed=True, match_kind="metadata"))

    assert "Embedded artwork differs" in explanation.conflicts
