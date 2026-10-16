from __future__ import annotations

from dataclasses import replace

from .path_safety import validate_library_pair
from .settings import Settings


def unavailable_libraries(library_a: str, library_b: str) -> tuple[str, ...]:
    """Return configured library labels whose saved roots are missing or unavailable."""
    result = []
    for label, value in (("library_a", library_a), ("library_b", library_b)):
        from pathlib import Path
        path = Path(value).expanduser() if value.strip() else None
        if path is None or not path.is_dir():
            result.append(label)
    return tuple(result)


def relink_settings(settings: Settings, library_a: str, library_b: str) -> Settings:
    """Return updated settings only after both replacement roots validate."""
    a, b = validate_library_pair(library_a, library_b)
    updated = replace(settings, library_a=str(a), library_b=str(b))
    updated.validate()
    return updated
