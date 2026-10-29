"""Load spirit personas and locate the project on disk."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Spirit:
    key: str
    name: str
    prompt_glyph: str
    blurb: str
    system_prompt: str
    canned_comments: tuple[str, ...]
    canned_moods: tuple[str, ...]
    canned_filename: str
    canned_body: str
    canned_subject: str
    canned_epitaph_body: str


def project_root() -> Path:
    """Directory that holds pyproject.toml and spirits/."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "spirits").is_dir():
            return parent
    return Path.cwd()


def spirits_dir() -> Path:
    override = os.environ.get("HAUNT_SPIRITS")
    if override:
        return Path(override)
    return project_root() / "spirits"


def load_spirits(directory: Path | None = None) -> dict[str, Spirit]:
    folder = directory or spirits_dir()
    if not folder.is_dir():
        raise FileNotFoundError(f"No spirits directory at {folder}")
    found: dict[str, Spirit] = {}
    for path in sorted(folder.glob("*.toml")):
        spirit = _load_one(path)
        found[spirit.key] = spirit
    if not found:
        raise FileNotFoundError(f"No spirit files in {folder}")
    return found


def _as_tuple(value: object, fallback: str) -> tuple[str, ...]:
    if isinstance(value, list) and value:
        return tuple(str(item) for item in value)
    return (fallback,)


def _load_one(path: Path) -> Spirit:
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    key = str(raw.get("key") or path.stem)
    comments = _as_tuple(raw.get("canned_comments"), "The spirit is present, but quiet.")
    moods = _as_tuple(raw.get("canned_moods"), "watching")
    system = str(raw.get("system_prompt") or "You haunt a terminal. Stay in character.").strip()
    blurb = str(raw.get("blurb") or system.splitlines()[0]).strip()
    return Spirit(
        key=key,
        name=str(raw.get("name") or key),
        prompt_glyph=str(raw.get("prompt_glyph") or ">"),
        blurb=blurb,
        system_prompt=system,
        canned_comments=comments,
        canned_moods=moods,
        canned_filename=str(raw.get("canned_filename") or "whisper.txt"),
        canned_body=str(raw.get("canned_body") or "A presence passed through this directory."),
        canned_subject=str(raw.get("canned_subject") or "Keep this change"),
        canned_epitaph_body=str(raw.get("canned_epitaph_body") or "Filed by the spirit on watch."),
    )
