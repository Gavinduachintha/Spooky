"""The possessed read-eval loop. Rituals never reach the operating system."""

from __future__ import annotations

import shlex
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Console

from haunted_terminal.epitaph import propose
from haunted_terminal.manifestations import banish, write_manifestation
from haunted_terminal.render import clean_mood, prompt_text, whisper, whisper_panel
from haunted_terminal.runner import run_command
from haunted_terminal.spirits import Spirit
from haunted_terminal.voice import CannedVoice, SpiritVoice

SPECIAL = {"git", "rm", "kill", "pkill"}


def split_command(command: str) -> list[str]:
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        return command.split()


def command_name(token: str) -> str:
    return Path(token).name.lower()


def names_in(command: str) -> set[str]:
    parts = split_command(command)
    if not parts:
        return set()
    names = {command_name(parts[0])}
    if command_name(parts[0]) == "sudo" and len(parts) > 1:
        names.add(command_name(parts[1]))
    return names


def should_speak(command: str, exit_code: int, turn: int, quiet: bool) -> bool:
    """Speak on failures and on git/rm/kill. Otherwise speak every second command."""
    if quiet or not command.strip():
        return False
    if exit_code != 0:
        return True
    if names_in(command) & SPECIAL:
        return True
    return turn % 2 == 0


@dataclass
class Session:
    cwd: Path
    spirits: dict[str, Spirit]
    spirit: Spirit
    voice: SpiritVoice
    console: Console
    confirm: Callable[[str], str] | None = None
    quiet: bool = False
    capture: bool = False
    mood: str = ""
    turns: int = 0
    since_mood: int = 0
    recent: list[dict[str, Any]] = field(default_factory=list)

    def boot(self) -> None:
        self._refresh_mood(force=True)

    def handle(self, line: str) -> bool:
        """Run one line. Return False when the session should end."""
        stripped = line.strip()
        if not stripped:
            return True
        if stripped in {"exit", "quit"}:
            return False
        if stripped.startswith("//"):
            self._run_user_command(stripped[2:].lstrip())
            return True
        if stripped.startswith("/"):
            return self._ritual(stripped)
        self._run_user_command(stripped)
        return True

    def prompt(self) -> str:
        return prompt_text(self.spirit, self.cwd, self.mood)

    def _ritual(self, line: str) -> bool:
        name, _, arg = line.partition(" ")
        name = name.lower()
        arg = arg.strip()
        if name in {"/exit", "/quit"}:
            return False
        if name == "/quiet":
            self.quiet = True
            self.console.print("The spirit holds its tongue.", markup=False, highlight=False)
            return True
        if name == "/loud":
            self.quiet = False
            self.console.print("The spirit speaks again.", markup=False, highlight=False)
            self._refresh_mood(force=True)
            return True
        if name == "/spirits":
            for spirit in self.spirits.values():
                mark = "*" if spirit.key == self.spirit.key else " "
                self.console.print(
                    f"{mark} {spirit.key}: {spirit.blurb}",
                    markup=False,
                    highlight=False,
                )
            return True
        if name == "/spirit":
            self._switch_spirit(arg)
            return True
        if name == "/manifest":
            self._manifest()
            return True
        if name == "/banish":
            removed = banish(self.cwd)
            self.console.print(f"Banished {removed} manifestation(s).", markup=False, highlight=False)
            return True
        if name == "/epitaph":
            message = propose(self.cwd, self.spirit, self.voice, self._context(), self._confirm)
            self.console.print(message, markup=False, highlight=False)
            return True
        self.console.print("The spirit does not know that rite.", markup=False, highlight=False)
        return True

    def _switch_spirit(self, arg: str) -> None:
        if not arg:
            known = ", ".join(self.spirits)
            self.console.print(f"Name a spirit: {known}", markup=False, highlight=False)
            return
        key = arg.split()[0].lower()
        spirit = self.spirits.get(key)
        if spirit is None:
            known = ", ".join(self.spirits)
            self.console.print(f"No spirit named {key}. Known: {known}", markup=False, highlight=False)
            return
        self.spirit = spirit
        self._refresh_mood(force=True)
        self.console.print(f"{spirit.name} takes the prompt. {spirit.blurb}", markup=False, highlight=False)

    def _manifest(self) -> None:
        drafted = self.voice.say(self.spirit, "manifest", self._context())
        if not isinstance(drafted, dict):
            drafted = CannedVoice().say(self.spirit, "manifest", self._context())
        assert isinstance(drafted, dict)
        path = write_manifestation(
            self.cwd,
            drafted.get("filename", ""),
            drafted.get("body", ""),
        )
        relative = path.relative_to(self.cwd.resolve())
        self.console.print(f"A file appeared: {relative.as_posix()}", markup=False, highlight=False)

    def _confirm(self, prompt: str) -> str:
        if self.confirm is not None:
            return self.confirm(prompt)
        self.console.print(prompt, markup=False, highlight=False, end="")
        try:
            return input("")
        except EOFError:
            return "n"

    def _run_user_command(self, command: str) -> None:
        if not command.strip():
            return
        code = self._dispatch(command)
        self.recent.append({"command": command, "exit_code": code})
        self.recent = self.recent[-4:]
        self.turns += 1
        self.since_mood += 1
        if should_speak(command, code, self.turns, self.quiet):
            self._speak(command, code)
        self._refresh_mood()

    def _dispatch(self, command: str) -> int:
        parts = split_command(command)
        if parts and command_name(parts[0]) == "cd":
            return self._cd(parts)
        if parts and command_name(parts[0]) == "pwd":
            self.console.print(str(self.cwd), markup=False, highlight=False)
            return 0
        try:
            code, output = run_command(command, self.cwd, capture=self.capture)
        except KeyboardInterrupt:
            return 130
        if self.capture and output:
            self.console.print(output, markup=False, highlight=False, end="" if output.endswith("\n") else "\n")
        return code

    def _cd(self, parts: list[str]) -> int:
        if len(parts) > 2:
            self.console.print("cd takes one path.", markup=False, highlight=False)
            return 1
        raw = parts[1] if len(parts) > 1 else "~"
        if raw == "~":
            target = Path.home()
        elif raw.startswith("~/"):
            target = Path.home() / raw[2:]
        else:
            target = Path(raw)
            if not target.is_absolute():
                target = self.cwd / target
        try:
            target = target.expanduser().resolve()
        except OSError:
            self.console.print("That path does not resolve.", markup=False, highlight=False)
            return 1
        if not target.is_dir():
            self.console.print(f"Not a directory: {raw}", markup=False, highlight=False)
            return 1
        self.cwd = target
        return 0

    def _speak(self, command: str, exit_code: int) -> None:
        context = self._context(command=command, exit_code=exit_code)
        if self.console.is_terminal:
            self._speak_streaming(context, exit_code)
            return
        text = self.voice.say(self.spirit, "comment", context, on_token=None)
        self._finish_whisper(text, exit_code)

    def _speak_streaming(self, context: dict[str, Any], exit_code: int) -> None:
        from rich.live import Live

        bucket = {"text": ""}
        panel = whisper_panel("", self.spirit.name, exit_code)

        def on_token(token: str) -> None:
            bucket["text"] += token
            live.update(whisper_panel(bucket["text"], self.spirit.name, exit_code))

        with Live(panel, console=self.console, refresh_per_second=8, transient=True) as live:
            text = self.voice.say(self.spirit, "comment", context, on_token=on_token)
        self._finish_whisper(text, exit_code)

    def _finish_whisper(self, text: str | dict[str, str], exit_code: int) -> None:
        if not isinstance(text, str):
            text = str(text)
        from_memory = bool(getattr(self.voice, "last_used_fallback", False))
        whisper(self.console, text, self.spirit.name, exit_code, from_memory=from_memory)

    def _refresh_mood(self, force: bool = False) -> None:
        if self.quiet:
            return
        if not force and self.mood and self.since_mood < 3:
            return
        raw = self.voice.say(self.spirit, "mood", self._context())
        self.mood = clean_mood(str(raw))
        self.since_mood = 0

    def _context(self, **extra: Any) -> dict[str, Any]:
        ctx: dict[str, Any] = {
            "cwd_name": self.cwd.name,
            "recent": [
                {"command": str(item["command"])[:180], "exit_code": int(item["exit_code"])}
                for item in self.recent[-4:]
            ],
        }
        ctx.update(extra)
        return ctx


def run_repl(session: Session) -> int:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory

    history_path = Path.home() / ".haunt" / "history"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_session = PromptSession(history=FileHistory(str(history_path)))
    session.boot()
    while True:
        try:
            line = prompt_session.prompt(session.prompt())
        except KeyboardInterrupt:
            continue
        except EOFError:
            session.console.print("The spirit recedes.", markup=False, highlight=False)
            return 0
        try:
            if not session.handle(line):
                session.console.print("The spirit recedes.", markup=False, highlight=False)
                return 0
        except KeyboardInterrupt:
            continue
