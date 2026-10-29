"""Prompt text and whisper panels."""

from __future__ import annotations

import re
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from haunted_terminal.spirits import Spirit


def short_cwd(cwd: Path) -> str:
    try:
        relative = cwd.resolve().relative_to(Path.home())
    except ValueError:
        return cwd.name or str(cwd)
    parts = [part for part in relative.parts if part not in {"", "."}]
    if not parts:
        return "~"
    if len(parts) > 3:
        return "~/" + parts[-1]
    return "~/" + "/".join(parts)


def prompt_text(spirit: Spirit, cwd: Path, mood: str) -> str:
    mood_bit = f" ({mood})" if mood else ""
    return f"{spirit.key}{mood_bit}:{short_cwd(cwd)} {spirit.prompt_glyph} "


def clean_mood(text: str) -> str:
    line = text.strip().splitlines()[0] if text.strip() else ""
    line = re.sub(r"[^A-Za-z0-9 '\-]", "", line).strip()
    words = line.split()
    line = " ".join(words[:2])
    return line[:24] or "watching"


def whisper_panel(
    text: str,
    spirit_name: str,
    exit_code: int | None,
    *,
    from_memory: bool = False,
) -> Panel:
    border = "bright_red" if exit_code else "medium_purple3"
    title = f"{spirit_name} whispers"
    if from_memory:
        title += " from memory"
    return Panel(
        Text(text.strip() or "...", style="italic"),
        title=title,
        title_align="left",
        border_style=border,
        padding=(0, 1),
    )


def whisper(
    console: Console,
    text: str,
    spirit_name: str,
    exit_code: int | None,
    *,
    from_memory: bool = False,
) -> None:
    console.print(whisper_panel(text, spirit_name, exit_code, from_memory=from_memory))
