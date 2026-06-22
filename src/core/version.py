"""Shared application version helpers."""

from pathlib import Path
from typing import Optional


DEFAULT_VERSION = "0.0.0"


def app_version(start: Optional[Path] = None) -> str:
    """Read the product version from the nearest VERSION file."""
    base = Path(start or __file__).resolve()
    candidates = []
    if base.is_file():
        candidates.append(base.parent / "VERSION")
        parents = base.parents
    else:
        candidates.append(base / "VERSION")
        parents = base.parents
    for parent in parents:
        candidates.append(parent / "VERSION")
    for candidate in candidates:
        try:
            value = candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return DEFAULT_VERSION


APP_VERSION = app_version()
