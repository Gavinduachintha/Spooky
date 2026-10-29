"""Command line entry for the haunted terminal."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from rich.console import Console

from haunted_terminal import __version__
from haunted_terminal.demo import run_demo
from haunted_terminal.repl import Session, run_repl
from haunted_terminal.spirits import load_spirits
from haunted_terminal.voice import (
    CannedVoice,
    OllamaVoice,
    ResilientVoice,
    VoiceError,
    local_base_url,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="haunt",
        description="A terminal possessed by a local spirit. Commands run on this machine. The model never does.",
    )
    parser.add_argument("--version", action="version", version=f"haunt {__version__}")
    parser.add_argument(
        "--model",
        default=os.environ.get("HAUNT_MODEL", "gemma3:1b"),
        help="Ollama model tag (default: gemma3:1b or HAUNT_MODEL)",
    )
    parser.add_argument(
        "--spirit",
        default=os.environ.get("HAUNT_SPIRIT", "poltergeist"),
        help="Starting spirit key",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("HAUNT_TIMEOUT", "8")),
        help="Seconds to wait for a whisper before using a canned line",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Record demo/session.txt with the canned voice, and try one live whisper",
    )
    args = parser.parse_args(argv)

    try:
        spirits = load_spirits()
        base_url = local_base_url(os.environ.get("OLLAMA_HOST"))
    except (FileNotFoundError, VoiceError) as exc:
        Console(stderr=True).print(str(exc), markup=False, highlight=False)
        return 2

    if args.spirit not in spirits:
        known = ", ".join(spirits)
        Console(stderr=True).print(
            f"No spirit named {args.spirit}. Known: {known}",
            markup=False,
            highlight=False,
        )
        return 2

    if args.demo:
        return run_demo(spirits, args.model, base_url, args.timeout)

    console = Console()
    voice, notes = _open_voice(args.model, base_url, args.timeout)
    spirit = spirits[args.spirit]
    console.print("Haunted Terminal", style="bold")
    console.print(
        "Commands run on this machine. Rituals start with /. The model never sees command output, and it never runs a shell.",
        markup=False,
        highlight=False,
    )
    console.print(
        "Rituals: /spirit  /spirits  /manifest  /banish  /epitaph  /quiet  /loud  /exit",
        markup=False,
        highlight=False,
    )
    console.print(f"Spirit: {spirit.name}    Model: {args.model}", markup=False, highlight=False)
    for note in notes:
        console.print(note, markup=False, highlight=False)

    session = Session(
        cwd=Path.cwd(),
        spirits=spirits,
        spirit=spirit,
        voice=voice,
        console=console,
    )
    return run_repl(session)


def _open_voice(model: str, base_url: str, timeout: float):
    fallback = CannedVoice()
    try:
        primary = OllamaVoice(model=model, base_url=base_url, timeout=timeout)
        status = primary.health()
    except VoiceError:
        return fallback, [
            "Ollama is not answering on the loopback address. The spirit will speak from memory. "
            "Start it with `ollama serve`, then `ollama pull " + model + "`."
        ]
    if not status.reachable:
        return fallback, [
            "Ollama is not answering on the loopback address. The spirit will speak from memory. "
            f"Start it with `ollama serve`, then `ollama pull {model}`."
        ]
    if not status.model_present:
        installed = ", ".join(status.models) or "none"
        return fallback, [
            f"The model {model} is not pulled (installed: {installed}). "
            f"Run `ollama pull {model}`. Until then the spirit speaks from memory."
        ]
    voice = ResilientVoice(primary, fallback)
    notes = ["The spirit is waking. Slow replies fall back to a canned line."]
    try:
        voice.warm()
    except VoiceError:
        notes.append("The weights did not finish waking. The first whispers may come from memory.")
    return voice, notes
