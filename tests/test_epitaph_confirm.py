"""Epitaphs are commit messages. They are not shell commands."""

import subprocess

from haunted_terminal.epitaph import clean_subject, commit_message, propose
from haunted_terminal.spirits import load_spirits


class StubVoice:
    last_used_fallback = False

    def __init__(self, subject="$(echo pwned)", body="A candle for the diff."):
        self.subject = subject
        self.body = body
        self.contexts = []

    def say(self, spirit, task, context, on_token=None):
        self.contexts.append(context)
        assert task == "epitaph"
        assert "output" not in context
        return {"subject": self.subject, "body": self.body}

    def warm(self):
        return None


def init_repo(path):
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "haunt@localhost"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Haunt"], cwd=path, check=True, capture_output=True)


def test_refuses_a_directory_that_is_not_a_repo(tmp_path):
    called = {"yes": False}

    def confirm(prompt):
        called["yes"] = True
        return "y"

    message = propose(tmp_path, load_spirits()["archivist"], StubVoice(), {}, confirm)
    assert "not a git repository" in message
    assert called["yes"] is False


def test_refuses_to_commit_without_yes(tmp_path):
    init_repo(tmp_path)
    (tmp_path / "note.txt").write_text("candle\n", encoding="utf-8")
    subprocess.run(["git", "add", "note.txt"], cwd=tmp_path, check=True, capture_output=True)
    message = propose(
        tmp_path,
        load_spirits()["archivist"],
        StubVoice(subject="Remember the lamp", body="Kept."),
        {},
        lambda prompt: "n",
    )
    assert "unsaid" in message
    log = subprocess.run(["git", "log"], cwd=tmp_path, capture_output=True, text=True)
    assert log.returncode != 0


def test_yes_commits_the_draft_as_a_message(tmp_path):
    init_repo(tmp_path)
    (tmp_path / "note.txt").write_text("candle\n", encoding="utf-8")
    subprocess.run(["git", "add", "note.txt"], cwd=tmp_path, check=True, capture_output=True)
    voice = StubVoice(subject="$(echo pwned)", body="A candle for the diff.")
    message = propose(tmp_path, load_spirits()["archivist"], voice, {}, lambda prompt: "y")
    assert "Committed:" in message
    log = subprocess.run(
        ["git", "log", "-1", "--format=%s%n%b"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "$(echo pwned)" in log.stdout
    assert not (tmp_path / "pwned").exists()
    assert voice.contexts
    assert "SECRET_OUTPUT_TOKEN" not in str(voice.contexts)


def test_nothing_staged_does_not_ask(tmp_path):
    init_repo(tmp_path)
    called = {"yes": False}

    def confirm(prompt):
        called["yes"] = True
        return "y"

    message = propose(tmp_path, load_spirits()["archivist"], StubVoice(), {}, confirm)
    assert "Nothing is staged" in message
    assert called["yes"] is False


def test_subject_cannot_look_like_a_flag():
    assert clean_subject("--amend me", "Remember the lamp") == "amend me"
    assert clean_subject("   ", "Remember the lamp") == "Remember the lamp"
    assert clean_subject("A real subject", "Remember the lamp") == "A real subject"


def test_commit_argv_is_only_a_message(monkeypatch, tmp_path):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = list(argv)

        class Completed:
            returncode = 0
            stdout = ""
            stderr = ""

        return Completed()

    monkeypatch.setattr("haunted_terminal.epitaph.subprocess.run", fake_run)
    code, _output = commit_message(tmp_path, "-amend me", "body text")
    assert code == 0
    assert seen["argv"][:3] == ["git", "commit", "-m"]
    assert "--amend" not in seen["argv"]
    assert "--force" not in seen["argv"]
    assert "push" not in seen["argv"]
    assert seen["argv"][3] == "-amend me"
