"""Ghost files that can only appear inside .haunt/manifestations/."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

MAX_BODY = 4000


class ManifestError(ValueError):
    """A ghost file tried to leave the sandbox."""


def sandbox_root(cwd: Path) -> Path:
    root = (cwd / ".haunt" / "manifestations").resolve()
    root.mkdir(parents=True, exist_ok=True)
    ignore = cwd / ".haunt" / ".gitignore"
    if not ignore.exists():
        ignore.parent.mkdir(parents=True, exist_ok=True)
        ignore.write_text("*\n", encoding="utf-8")
    return root


def safe_filename(name: str) -> str:
    base = Path(str(name).replace("\\", "/")).name.replace("\x00", "")
    if base in {"", ".", ".."}:
        return "whisper.txt"
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", base).strip("._")
    if not cleaned:
        return "whisper.txt"
    return cleaned[:80]


def destination(cwd: Path, name: str) -> Path:
    root = sandbox_root(cwd)
    dest = (root / safe_filename(name)).resolve()
    if not dest.is_relative_to(root):
        raise ManifestError(name)
    return dest


def write_manifestation(cwd: Path, filename: str, body: str) -> Path:
    path = destination(cwd, filename)
    text = str(body)[:MAX_BODY]
    path.write_text(text, encoding="utf-8")
    return path


def banish(cwd: Path) -> int:
    root = cwd / ".haunt" / "manifestations"
    if not root.exists():
        return 0
    removed = 0
    for child in list(root.iterdir()):
        if child.is_file() or child.is_symlink():
            child.unlink()
            removed += 1
        elif child.is_dir():
            shutil.rmtree(child)
            removed += 1
    return removed
