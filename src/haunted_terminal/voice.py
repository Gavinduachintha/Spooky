"""Local Ollama client and the canned voice used when it cannot answer."""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Any, Callable, Protocol
from urllib.parse import urlparse

from haunted_terminal.spirits import Spirit

NUM_CTX = 4096
KEEP_ALIVE = "30m"
DEFAULT_TIMEOUT = 8.0
WARM_TIMEOUT = 45.0
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}

Opener = Callable[..., Any]

MANIFEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "filename": {"type": "string"},
        "body": {"type": "string"},
    },
    "required": ["filename", "body"],
}

EPITAPH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "body": {"type": "string"},
    },
    "required": ["subject", "body"],
}

TASK_OPTIONS: dict[str, dict[str, float | int]] = {
    "comment": {"temperature": 0.9, "num_predict": 70},
    "mood": {"temperature": 0.7, "num_predict": 12},
    "manifest": {"temperature": 0.4, "num_predict": 220},
    "epitaph": {"temperature": 0.4, "num_predict": 180},
}

TASK_HINTS = {
    "comment": (
        "React in one or two short sentences to the latest command and its exit code. "
        "Do not explain how to fix it. Do not repeat the command. Do not use a code block."
    ),
    "mood": "Reply with one or two words naming your mood. No punctuation.",
    "manifest": (
        "Invent a single ghost file about this session. "
        "Respond in JSON with keys filename and body."
    ),
    "epitaph": (
        "Write a git commit message in character. "
        "Respond in JSON with keys subject and body. "
        "subject is one line under 72 characters."
    ),
}


class VoiceError(Exception):
    """The local model could not answer."""


class DaemonStatus:
    def __init__(self, reachable: bool, model_present: bool, models: tuple[str, ...]):
        self.reachable = reachable
        self.model_present = model_present
        self.models = models


class SpiritVoice(Protocol):
    last_used_fallback: bool

    def say(
        self,
        spirit: Spirit,
        task: str,
        context: dict[str, Any],
        on_token: Callable[[str], None] | None = None,
    ) -> str | dict[str, str]: ...

    def warm(self) -> None: ...


def local_base_url(raw: str | None) -> str:
    """Accept only a loopback Ollama origin."""
    text = (raw or "http://127.0.0.1:11434").strip()
    if "://" not in text:
        text = "http://" + text
    parsed = urlparse(text)
    host = parsed.hostname
    if parsed.scheme != "http" or host not in LOCAL_HOSTS:
        raise VoiceError(
            "Haunted Terminal only talks to Ollama on 127.0.0.1, localhost, or ::1."
        )
    port = parsed.port or 11434
    if ":" in host:
        return f"http://[{host}]:{port}"
    return f"http://{host}:{port}"


def shrink_context(context: dict[str, Any]) -> dict[str, Any]:
    """Keep the prompt small. Unknown keys, including command output, are dropped."""
    recent_in = list(context.get("recent") or [])[-4:]
    recent: list[dict[str, Any]] = []
    for item in recent_in:
        if not isinstance(item, dict):
            continue
        recent.append(
            {
                "command": str(item.get("command", ""))[:180],
                "exit_code": _code(item.get("exit_code", 0)),
            }
        )
    return {
        "cwd_name": str(context.get("cwd_name", ""))[:80],
        "command": str(context.get("command", ""))[:180],
        "exit_code": _code(context.get("exit_code", 0)),
        "recent": recent,
        "summary": str(context.get("summary", ""))[:1500],
    }


def _code(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _format_recent(recent: list[dict[str, Any]]) -> str:
    if not recent:
        return "(none)"
    lines = []
    for item in recent:
        lines.append(f"- `{item['command']}` -> exit {item['exit_code']}")
    return "\n".join(lines)


def build_messages(spirit: Spirit, task: str, context: dict[str, Any]) -> list[dict[str, str]]:
    hint = TASK_HINTS.get(task, TASK_HINTS["comment"])
    system = f"{spirit.system_prompt.strip()}\n\n{hint}"
    ctx = shrink_context(context)
    if task == "mood":
        user = (
            f"Directory: {ctx['cwd_name']}\n"
            f"Recent commands:\n{_format_recent(ctx['recent'])}\n"
            "Name your mood in one or two words."
        )
    elif task == "manifest":
        user = (
            f"Directory: {ctx['cwd_name']}\n"
            f"Recent commands:\n{_format_recent(ctx['recent'])}\n"
            "Invent one ghost file tied to this session. Respond in JSON."
        )
    elif task == "epitaph":
        user = (
            f"Directory: {ctx['cwd_name']}\n"
            f"Git summary:\n{ctx['summary']}\n"
            "Write the commit message. Respond in JSON."
        )
    else:
        user = (
            f"Directory: {ctx['cwd_name']}\n"
            f"Recent commands:\n{_format_recent(ctx['recent'])}\n"
            f"Latest command: `{ctx['command']}`\n"
            f"Exit code: {ctx['exit_code']}\n"
            "Whisper in character."
        )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def parse_model_json(text: str) -> dict[str, str]:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.strip("`")
        if candidate.lower().startswith("json"):
            candidate = candidate[4:]
        candidate = candidate.strip()
    try:
        loaded = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start < 0 or end <= start:
            raise VoiceError("The model did not return JSON.") from None
        try:
            loaded = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError as exc:
            raise VoiceError("The model did not return JSON.") from exc
    if not isinstance(loaded, dict):
        raise VoiceError("The model did not return a JSON object.")
    return {str(key): "" if value is None else str(value) for key, value in loaded.items()}


def model_is_present(wanted: str, names: tuple[str, ...]) -> bool:
    if wanted in names:
        return True
    # "gemma3" matches an installed "gemma3:1b". A specific tag must match exactly.
    if ":" in wanted:
        return False
    return any(name.split(":")[0] == wanted for name in names)


class CannedVoice:
    """Hand-written lines. Used in tests and whenever Ollama cannot answer."""

    last_used_fallback = True

    def say(
        self,
        spirit: Spirit,
        task: str,
        context: dict[str, Any],
        on_token: Callable[[str], None] | None = None,
    ) -> str | dict[str, str]:
        del on_token
        if task == "mood":
            return spirit.canned_moods[0]
        if task == "manifest":
            return {"filename": spirit.canned_filename, "body": spirit.canned_body}
        if task == "epitaph":
            return {"subject": spirit.canned_subject, "body": spirit.canned_epitaph_body}
        lines = spirit.canned_comments
        if _code(context.get("exit_code", 0)) != 0 and lines:
            return lines[-1]
        pool = lines[:-1] or lines
        return _pick(pool, str(context.get("command", "")))

    def warm(self) -> None:
        return None


class OllamaVoice:
    """POST /api/chat on a loopback Ollama server. No SDK."""

    last_used_fallback = False

    def __init__(
        self,
        model: str,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        opener: Opener | None = None,
    ):
        self.model = model
        self.base_url = local_base_url(base_url)
        self.timeout = timeout
        self.opener = opener or urllib.request.urlopen

    def health(self) -> DaemonStatus:
        try:
            with self._open("GET", "/api/tags", None, timeout=3) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (VoiceError, json.JSONDecodeError, UnicodeError):
            return DaemonStatus(False, False, ())
        names = tuple(
            str(item.get("name", ""))
            for item in body.get("models", [])
            if isinstance(item, dict)
        )
        return DaemonStatus(True, model_is_present(self.model, names), names)

    def warm(self) -> None:
        self._complete(
            [{"role": "user", "content": "Say: awake"}],
            temperature=0,
            num_predict=1,
            timeout=WARM_TIMEOUT,
        )

    def say(
        self,
        spirit: Spirit,
        task: str,
        context: dict[str, Any],
        on_token: Callable[[str], None] | None = None,
    ) -> str | dict[str, str]:
        options = TASK_OPTIONS.get(task, TASK_OPTIONS["comment"])
        messages = build_messages(spirit, task, context)
        schema = None
        if task == "manifest":
            schema = MANIFEST_SCHEMA
        elif task == "epitaph":
            schema = EPITAPH_SCHEMA
        stream = task == "comment" and on_token is not None
        if stream:
            text = "".join(
                self._stream(
                    messages,
                    temperature=float(options["temperature"]),
                    num_predict=int(options["num_predict"]),
                    on_token=on_token,
                )
            )
        else:
            text = self._complete(
                messages,
                temperature=float(options["temperature"]),
                num_predict=int(options["num_predict"]),
                schema=schema,
            )
        if task in {"manifest", "epitaph"}:
            return parse_model_json(text)
        return text.strip()

    def _complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        num_predict: int,
        timeout: float | None = None,
        schema: dict[str, Any] | None = None,
    ) -> str:
        payload = self._payload(messages, temperature, num_predict, schema, stream=False)
        try:
            with self._open("POST", "/api/chat", payload, timeout=timeout or self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise VoiceError("Ollama returned something that was not JSON.") from exc
        message = body.get("message") if isinstance(body, dict) else None
        if not isinstance(message, dict):
            raise VoiceError("Ollama returned no message.")
        return str(message.get("content") or "")

    def _stream(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        num_predict: int,
        on_token: Callable[[str], None] | None,
    ):
        import time

        payload = self._payload(messages, temperature, num_predict, None, stream=True)
        deadline = time.monotonic() + self.timeout
        response = self._open("POST", "/api/chat", payload, timeout=self.timeout)
        with response:
            while True:
                if time.monotonic() >= deadline:
                    raise VoiceError("Ollama did not answer in time.")
                try:
                    line = response.readline()
                except (TimeoutError, socket.timeout):
                    raise VoiceError("Ollama did not answer in time.") from None
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    chunk = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise VoiceError("Ollama sent a broken stream.") from exc
                message = chunk.get("message") if isinstance(chunk, dict) else None
                token = ""
                if isinstance(message, dict):
                    token = str(message.get("content") or "")
                if token:
                    if on_token is not None:
                        on_token(token)
                    yield token
                if isinstance(chunk, dict) and chunk.get("done"):
                    break

    def _payload(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        num_predict: int,
        schema: dict[str, Any] | None,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            "keep_alive": KEEP_ALIVE,
            "options": {
                "temperature": temperature,
                "num_predict": num_predict,
                "num_ctx": NUM_CTX,
            },
        }
        if schema is not None:
            payload["format"] = schema
        return payload

    def _open(self, method: str, path: str, payload: dict[str, Any] | None, timeout: float):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            return self.opener(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            raise VoiceError(f"Ollama returned HTTP {exc.code}.") from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise VoiceError("Ollama did not answer in time.") from exc


class ResilientVoice:
    """Try Ollama, and if it fails return a canned line instead of freezing."""

    def __init__(self, primary: OllamaVoice, fallback: CannedVoice | None = None):
        self.primary = primary
        self.fallback = fallback or CannedVoice()
        self.last_used_fallback = False

    def say(
        self,
        spirit: Spirit,
        task: str,
        context: dict[str, Any],
        on_token: Callable[[str], None] | None = None,
    ) -> str | dict[str, str]:
        try:
            result = self.primary.say(spirit, task, context, on_token=on_token)
        except (VoiceError, TimeoutError, json.JSONDecodeError, OSError, KeyError, TypeError, ValueError):
            self.last_used_fallback = True
            return self.fallback.say(spirit, task, context)
        self.last_used_fallback = False
        return result

    def warm(self) -> None:
        self.primary.warm()


def _pick(lines: tuple[str, ...], seed: str) -> str:
    if not lines:
        return "The spirit is present, but quiet."
    index = sum(ord(char) for char in seed) % len(lines)
    return lines[index]
