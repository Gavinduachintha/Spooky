"""Run a user-typed command. Output is for the terminal, never for the model."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def bash_executable() -> str | None:
    """Git Bash (or any bash) on Windows. Login shells are avoided so rc files cannot cd away."""
    if os.name != "nt":
        return None
    shell = os.environ.get("SHELL", "")
    if os.environ.get("MSYSTEM") or "bash" in shell.lower() or shutil.which("bash"):
        return shutil.which("bash")
    return None


def run_command(command: str, cwd: Path, *, capture: bool = False) -> tuple[int, str]:
    kwargs: dict = {
        "cwd": cwd,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if capture:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.STDOUT
    bash = bash_executable()
    if bash:
        completed = subprocess.run([bash, "-c", command], **kwargs)
    else:
        completed = subprocess.run(command, shell=True, **kwargs)
    output = completed.stdout or "" if capture else ""
    code = completed.returncode if completed.returncode is not None else 1
    return code, output
