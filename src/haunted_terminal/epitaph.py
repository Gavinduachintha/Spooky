"""Draft a commit message and commit only after an explicit yes."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from haunted_terminal.spirits import Spirit
from haunted_terminal.voice import CannedVoice, SpiritVoice


def git_available(cwd: Path) -> bool:
    completed = _git(cwd, ["rev-parse", "--is-inside-work-tree"])
    return completed.returncode == 0 and (completed.stdout or "").strip() == "true"


def has_staged_changes(cwd: Path) -> bool:
    completed = _git(cwd, ["diff", "--cached", "--quiet"])
    return completed.returncode == 1


def git_summary(cwd: Path) -> str:
    status = _git(cwd, ["status", "--short"])
    staged = _git(cwd, ["diff", "--cached", "--stat"])
    status_text = (status.stdout or "").strip()[:800]
    staged_text = (staged.stdout or "").strip()[:700]
    return f"status:\n{status_text}\n\nstaged stat:\n{staged_text}"


def clean_subject(subject: str, fallback: str) -> str:
    collapsed = " ".join(str(subject).split())
    collapsed = collapsed.lstrip("-").strip()
    if not collapsed:
        collapsed = fallback
    return collapsed[:72]


def clean_body(body: str, fallback: str) -> str:
    text = str(body).strip()
    if not text:
        text = fallback
    return text[:2000]


def propose(
    cwd: Path,
    spirit: Spirit,
    voice: SpiritVoice,
    context: dict[str, Any],
    confirm: Callable[[str], str],
) -> str:
    if not git_available(cwd):
        return "This directory is not a git repository. Nothing was committed."
    if not has_staged_changes(cwd):
        return (
            "Nothing is staged. git add the files you want remembered, "
            "then /epitaph again. Nothing was committed."
        )
    payload = dict(context)
    payload["summary"] = git_summary(cwd)
    payload["cwd_name"] = cwd.name
    drafted = voice.say(spirit, "epitaph", payload)
    if not isinstance(drafted, dict):
        drafted = CannedVoice().say(spirit, "epitaph", payload)
        assert isinstance(drafted, dict)
    subject = clean_subject(drafted.get("subject", ""), spirit.canned_subject)
    body = clean_body(drafted.get("body", ""), spirit.canned_epitaph_body)
    answer = confirm(
        "Commit with this epitaph?\n\n"
        f"{subject}\n\n{body}\n\n"
        "Type y to commit: "
    )
    if answer.strip().lower() not in {"y", "yes"}:
        return "The epitaph was left unsaid. Nothing was committed."
    code, output = commit_message(cwd, subject, body)
    if code != 0:
        detail = output.strip() or "git commit failed."
        return f"git refused the burial.\n{detail}"
    return f"Committed: {subject}"


def commit_message(cwd: Path, subject: str, body: str) -> tuple[int, str]:
    argv = ["git", "commit", "-m", subject, "-m", body]
    if "--force" in argv or "--amend" in argv or "push" in argv:
        raise RuntimeError("Refusing an unsafe git invocation.")
    completed = subprocess.run(
        argv,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    return completed.returncode, output


def _git(cwd: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
