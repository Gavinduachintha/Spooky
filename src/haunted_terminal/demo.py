"""Scripted session used to record demo/session.txt without a network."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from rich.console import Console

from haunted_terminal.repl import Session
from haunted_terminal.spirits import Spirit, project_root
from haunted_terminal.voice import CannedVoice, OllamaVoice, VoiceError

DEMO_LINES = [
    "echo The terminal flickers.",
    "ls no-such-candle",
    "/spirits",
    "/spirit archivist",
    "/manifest",
    "ls .haunt/manifestations",
    "git add note.txt",
    "/epitaph",
    "git log -1 --format=%s",
    "/quiet",
    "git status",
    "/loud",
    "/spirit keeper",
    "ls no-such-lamp",
    "/banish",
]


def run_demo(spirits: dict[str, Spirit], model: str, base_url: str | None, timeout: float) -> int:
    root = project_root()
    demo_dir = root / "demo"
    demo_dir.mkdir(parents=True, exist_ok=True)
    transcript = _scripted_transcript(spirits)
    (demo_dir / "session.txt").write_text(transcript, encoding="utf-8")
    live = _live_whisper(spirits, model, base_url, timeout)
    (demo_dir / "live-whisper.txt").write_text(live, encoding="utf-8")
    print(f"Wrote {demo_dir / 'session.txt'}")
    print(f"Wrote {demo_dir / 'live-whisper.txt'}")
    return 0


def _scripted_transcript(spirits: dict[str, Spirit]) -> str:
    from io import StringIO

    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, no_color=True, width=100)
    with tempfile.TemporaryDirectory(prefix="haunt-demo-") as temporary:
        work = Path(temporary)
        _git(work, ["init"])
        _git(work, ["config", "user.email", "haunt@localhost"])
        _git(work, ["config", "user.name", "Haunt"])
        (work / "note.txt").write_text("a candle for the last commit\n", encoding="utf-8")
        session = Session(
            cwd=work,
            spirits=spirits,
            spirit=spirits["poltergeist"],
            voice=CannedVoice(),
            console=console,
            confirm=_yes(console),
            capture=True,
        )
        session.boot()
        console.print(
            "Haunted Terminal demo. This transcript uses the canned voice, so it runs with the network off.",
            markup=False,
            highlight=False,
        )
        for line in DEMO_LINES:
            console.print(session.prompt() + line, markup=False, highlight=False)
            session.handle(line)
    return buffer.getvalue()


def _yes(console: Console):
    def confirm(prompt: str) -> str:
        console.print(prompt, markup=False, highlight=False)
        console.print("y", markup=False, highlight=False)
        return "y"

    return confirm


def _live_whisper(
    spirits: dict[str, Spirit],
    model: str,
    base_url: str | None,
    timeout: float,
) -> str:
    spirit = spirits["archivist"]
    try:
        voice = OllamaVoice(model=model, base_url=base_url, timeout=max(timeout, 60))
        status = voice.health()
    except VoiceError as exc:
        return _offline_note(model, str(exc))
    if not status.reachable:
        return _offline_note(model, "Ollama did not answer on the loopback port.")
    if not status.model_present:
        return _offline_note(
            model,
            f"{model} is not pulled. Installed models: {', '.join(status.models) or '(none)'}.",
        )
    context = {
        "cwd_name": "haunted-terminal",
        "command": "ls no-such-candle",
        "exit_code": 2,
        "recent": [{"command": "ls no-such-candle", "exit_code": 2}],
    }
    try:
        text = voice.say(spirit, "comment", context)
    except VoiceError as exc:
        return _offline_note(model, str(exc))
    if not isinstance(text, str) or not text.strip():
        return _offline_note(model, "The model returned an empty comment.")
    return (
        f"Live reply from {model} as the {spirit.name}, on the loopback Ollama API.\n"
        "Command: ls no-such-candle (exit 2)\n\n"
        f"{text.strip()}\n"
    )


def _offline_note(model: str, reason: str) -> str:
    return (
        "No live model reply was captured.\n"
        f"Reason: {reason}\n\n"
        "The shell still runs. When Ollama is down or slower than the timeout, "
        "whispers come from the spirit's canned lines, and the panel says so.\n"
        f"For a live spirit: ollama serve, then ollama pull {model}, then haunt.\n"
        "After the model is on disk, unplug the network. Inference stays on 127.0.0.1.\n"
    )


def _git(cwd: Path, args: list[str]) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
