"""Rituals, commentary policy, and the boundary between the shell and the model."""

import json
import subprocess
from io import StringIO

from rich.console import Console

from haunted_terminal.repl import Session, should_speak
from haunted_terminal.runner import bash_executable
from haunted_terminal.spirits import load_spirits
from haunted_terminal.voice import CannedVoice


class RecordingVoice(CannedVoice):
    def __init__(self):
        self.calls = []

    def say(self, spirit, task, context, on_token=None):
        self.calls.append((task, context))
        return super().say(spirit, task, context, on_token)


def make_session(tmp_path, voice=None):
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, no_color=True, width=120)
    spirits = load_spirits()
    voice = voice or RecordingVoice()
    session = Session(
        cwd=tmp_path,
        spirits=spirits,
        spirit=spirits["poltergeist"],
        voice=voice,
        console=console,
        capture=True,
    )
    return session, buffer


def comments(voice: RecordingVoice):
    return [context for task, context in voice.calls if task == "comment"]


def test_policy_matrix():
    assert should_speak("", 0, 2, quiet=False) is False
    assert should_speak("echo hi", 0, 1, quiet=False) is False
    assert should_speak("echo hi", 0, 2, quiet=False) is True
    assert should_speak("echo hi", 0, 2, quiet=True) is False
    assert should_speak("ls missing", 2, 1, quiet=False) is True
    assert should_speak("git status", 0, 3, quiet=False) is True
    assert should_speak("sudo rm -rf build", 0, 1, quiet=False) is True
    assert should_speak("kill 1", 0, 1, quiet=False) is True


def test_odd_success_is_silent_and_failure_is_not(tmp_path):
    session, _buffer = make_session(tmp_path)
    session.boot()
    session.handle("echo one")
    assert comments(session.voice) == []
    session.handle("ls no-such-candle")
    assert len(comments(session.voice)) == 1
    dumped = json.dumps(comments(session.voice))
    assert "output" not in comments(session.voice)[0]
    assert "no-such-candle" in dumped


def test_git_speaks_on_an_odd_successful_turn(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    session, _buffer = make_session(tmp_path)
    session.boot()
    session.handle("echo one")
    session.handle("echo two")
    before = len(comments(session.voice))
    session.handle("git status")
    spoken = comments(session.voice)
    assert len(spoken) == before + 1
    assert spoken[-1]["command"].startswith("git status")
    assert spoken[-1]["exit_code"] == 0


def test_command_output_is_not_sent_to_the_voice(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("SECRET_OUTPUT_TOKEN\n", encoding="utf-8")
    show = "cat secret.txt" if bash_executable() or __import__("os").name != "nt" else "type secret.txt"
    session, buffer = make_session(tmp_path)
    session.boot()
    session.handle("echo one")
    session.handle(show)
    assert "SECRET_OUTPUT_TOKEN" in buffer.getvalue()
    assert "SECRET_OUTPUT_TOKEN" not in json.dumps(session.voice.calls)


def test_quiet_suppresses_a_failure(tmp_path):
    session, buffer = make_session(tmp_path)
    session.boot()
    assert session.handle("/quiet") is True
    session.handle("ls no-such-candle")
    assert comments(session.voice) == []
    assert "holds its tongue" in buffer.getvalue()
    session.handle("/loud")
    session.handle("ls no-such-candle")
    assert len(comments(session.voice)) == 1


def test_spirit_switch_and_unknown_rite(tmp_path):
    session, buffer = make_session(tmp_path)
    session.handle("/spirits")
    text = buffer.getvalue()
    assert "archivist" in text
    assert "keeper" in text
    session.handle("/spirit archivist")
    assert session.spirit.key == "archivist"
    assert "remembering" in session.mood or session.mood in session.spirit.canned_moods
    session.handle("/spirit nobody")
    assert session.spirit.key == "archivist"
    session.handle("/dance")
    assert "does not know" in buffer.getvalue()


def test_manifest_and_cd_stay_in_session(tmp_path):
    session, buffer = make_session(tmp_path)
    nested = tmp_path / "cellar"
    nested.mkdir()
    session.handle("/manifest")
    ghost = tmp_path / ".haunt" / "manifestations" / "cold-breath.txt"
    assert ghost.is_file()
    assert "cold-breath.txt" in buffer.getvalue()
    session.handle("/banish")
    assert not ghost.exists()
    assert "Banished" in buffer.getvalue()
    session.handle("cd cellar")
    assert session.cwd == nested.resolve()
    session.handle("pwd")
    assert str(nested.resolve()) in buffer.getvalue()
    session.handle("cd missing-room")
    assert session.cwd == nested.resolve()


def test_slash_escape_runs_a_command(tmp_path):
    session, buffer = make_session(tmp_path)
    session.boot()
    assert session.handle("//echo escaped-rite") is True
    assert "escaped-rite" in buffer.getvalue()
    assert "does not know" not in buffer.getvalue()


def test_exit_ends_the_session(tmp_path):
    session, _buffer = make_session(tmp_path)
    assert session.handle("exit") is False
    assert session.handle("/quit") is False
