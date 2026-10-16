from pathlib import Path

import pytest
from PIL import Image

from harmelune import artwork


class FakeID3:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.frames = []
        self.fail_save = False

    def getall(self, _key):
        return self.frames

    def delall(self, _key):
        self.frames = []

    def add(self, frame):
        self.frames.append(frame)

    def save(self, path=None):
        if self.fail_save:
            raise OSError("simulated artwork write failure")
        target = Path(path) if path else self.path
        target.write_bytes(b"updated-audio-with-cover")


def make_image(path: Path):
    Image.new("RGB", (12, 8), "blue").save(path, format="PNG")
    return path


def test_mp3_replacement_backs_up_original_and_writes_new_artwork(tmp_path: Path, monkeypatch):
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"original-audio")
    image = make_image(tmp_path / "cover.png")
    fake = FakeID3(audio)
    monkeypatch.setattr(artwork, "ID3", lambda path=None: fake)
    monkeypatch.setattr(artwork, "APIC", lambda **kwargs: kwargs)

    backup = artwork.replace_artwork(audio, image, tmp_path.parent / f"{tmp_path.name}-backups")

    assert backup.read_bytes() == b"original-audio"
    assert audio.read_bytes() == b"updated-audio-with-cover"
    assert fake.frames[0]["mime"] == "image/png"


def test_failed_artwork_write_restores_original(tmp_path: Path, monkeypatch):
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"original-audio")
    image = make_image(tmp_path / "cover.png")
    fake = FakeID3(audio)
    fake.fail_save = True
    monkeypatch.setattr(artwork, "ID3", lambda path=None: fake)
    monkeypatch.setattr(artwork, "APIC", lambda **kwargs: kwargs)

    with pytest.raises(artwork.ArtworkRepairError, match="original file was restored"):
        artwork.replace_artwork(audio, image, tmp_path.parent / f"{tmp_path.name}-backups")
    assert audio.read_bytes() == b"original-audio"


def test_rejects_unsupported_audio_and_invalid_image(tmp_path: Path):
    audio = tmp_path / "song.ogg"
    audio.write_bytes(b"audio")
    image = tmp_path / "cover.txt"
    image.write_text("not an image", encoding="utf-8")
    with pytest.raises(ValueError, match="not supported"):
        artwork.replace_artwork(audio, image, tmp_path.parent / f"{tmp_path.name}-backups")

    mp3 = tmp_path / "song.mp3"
    mp3.write_bytes(b"audio")
    with pytest.raises(ValueError, match="invalid or unsupported"):
        artwork.replace_artwork(mp3, image, tmp_path.parent / f"{tmp_path.name}-backups")


def test_rejects_backup_location_inside_audio_folder(tmp_path: Path, monkeypatch):
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"audio")
    image = make_image(tmp_path / "cover.png")
    fake = FakeID3(audio)
    monkeypatch.setattr(artwork, "ID3", lambda path=None: fake)
    monkeypatch.setattr(artwork, "APIC", lambda **kwargs: kwargs)
    with pytest.raises(ValueError, match="separate"):
        artwork.replace_artwork(audio, image, tmp_path / "backups")
