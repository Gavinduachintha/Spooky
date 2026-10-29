"""Ollama client: loopback only, short prompts, canned fallback."""

import json

import pytest

from haunted_terminal.spirits import load_spirits
from haunted_terminal.voice import (
    CannedVoice,
    OllamaVoice,
    ResilientVoice,
    VoiceError,
    local_base_url,
)


class JSONResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args) -> bool:
        return False


class StreamResponse:
    def __init__(self, lines: list[bytes]):
        self._lines = list(lines)

    def readline(self) -> bytes:
        if not self._lines:
            return b""
        return self._lines.pop(0)

    def __enter__(self):
        return self

    def __exit__(self, *args) -> bool:
        return False


class FakeAPI:
    def __init__(self, content: str = "boo", models: list[str] | None = None, tokens: tuple[str, ...] = ("Bo", "o")):
        self.requests: list[dict] = []
        self.content = content
        self.models = models if models is not None else ["gemma3:1b"]
        self.tokens = tokens

    def __call__(self, request, timeout=None):
        payload = None if request.data is None else json.loads(request.data.decode())
        self.requests.append(
            {
                "url": request.full_url,
                "method": request.get_method(),
                "payload": payload,
                "timeout": timeout,
            }
        )
        if request.get_method() == "GET":
            body = {"models": [{"name": name} for name in self.models]}
            return JSONResponse(json.dumps(body).encode())
        if payload and payload.get("stream"):
            lines = [
                (json.dumps({"message": {"content": token}, "done": False}) + "\n").encode()
                for token in self.tokens
            ]
            lines.append(b'{"done": true}\n')
            return StreamResponse(lines)
        return JSONResponse(json.dumps({"message": {"content": self.content}}).encode())


def spirit():
    return load_spirits()["poltergeist"]


def test_loopback_only():
    assert local_base_url(None) == "http://127.0.0.1:11434"
    assert local_base_url("http://localhost:11434/") == "http://localhost:11434"
    assert local_base_url("http://[::1]:11434") == "http://[::1]:11434"
    with pytest.raises(VoiceError):
        local_base_url("http://0.0.0.0:11434")
    with pytest.raises(VoiceError):
        local_base_url("http://example.com:11434")
    with pytest.raises(VoiceError):
        local_base_url("https://127.0.0.1:11434")


def test_chat_payload_is_small_and_drops_command_output():
    api = FakeAPI()
    voice = OllamaVoice("gemma3:1b", opener=api, timeout=8)
    recent = [{"command": "OLDCOMMANDMARKER", "exit_code": 0}]
    recent.extend({"command": f"cmd{i}", "exit_code": 0} for i in range(5))
    voice.say(
        spirit(),
        "comment",
        {
            "output": "SECRET_OUTPUT_TOKEN",
            "stdout": "SECRET_OUTPUT_TOKEN",
            "command": "A" * 500,
            "exit_code": 0,
            "cwd_name": "proj",
            "recent": recent,
        },
    )
    payload = api.requests[-1]["payload"]
    encoded = json.dumps(payload)
    assert payload["options"]["num_ctx"] == 4096
    assert payload["options"]["temperature"] == 0.9
    assert payload["options"]["num_predict"] == 70
    assert payload["stream"] is False
    assert payload["keep_alive"] == "30m"
    assert "SECRET_OUTPUT_TOKEN" not in encoded
    assert "OLDCOMMANDMARKER" not in encoded
    assert "cmd4" in encoded
    assert "A" * 181 not in encoded
    assert api.requests[-1]["timeout"] == 8


def test_manifest_asks_for_json_schema():
    api = FakeAPI(content=json.dumps({"filename": "../x.txt", "body": "candle"}))
    voice = OllamaVoice("gemma3:1b", opener=api)
    parsed = voice.say(spirit(), "manifest", {"cwd_name": "proj", "recent": []})
    payload = api.requests[-1]["payload"]
    assert payload["format"]["required"] == ["filename", "body"]
    assert payload["options"]["temperature"] == 0.4
    assert "JSON" in payload["messages"][0]["content"]
    assert parsed == {"filename": "../x.txt", "body": "candle"}


def test_stream_assembles_tokens():
    api = FakeAPI()
    voice = OllamaVoice("gemma3:1b", opener=api, timeout=8)
    seen: list[str] = []
    text = voice.say(spirit(), "comment", {"command": "ls", "exit_code": 0}, on_token=seen.append)
    assert text == "Boo"
    assert seen == ["Bo", "o"]
    assert api.requests[-1]["payload"]["stream"] is True


def test_timeout_falls_back_to_canned_line():
    def opener(request, timeout=None):
        raise TimeoutError("slow")

    primary = OllamaVoice("gemma3:1b", opener=opener, timeout=8)
    voice = ResilientVoice(primary, CannedVoice())
    text = voice.say(spirit(), "comment", {"command": "ls", "exit_code": 2, "cwd_name": "proj"})
    assert text in spirit().canned_comments
    assert voice.last_used_fallback is True


def test_bad_json_falls_back_to_canned_manifest():
    api = FakeAPI(content="not json at all")
    primary = OllamaVoice("gemma3:1b", opener=api)
    with pytest.raises(VoiceError):
        primary.say(spirit(), "manifest", {"cwd_name": "proj"})
    voice = ResilientVoice(primary, CannedVoice())
    parsed = voice.say(spirit(), "manifest", {"cwd_name": "proj"})
    assert parsed == {"filename": spirit().canned_filename, "body": spirit().canned_body}
    assert voice.last_used_fallback is True


def test_health_sees_pulled_model_and_refuses_a_different_tag():
    present = OllamaVoice("gemma3:1b", opener=FakeAPI(models=["gemma3:1b"]))
    status = present.health()
    assert status.reachable is True
    assert status.model_present is True

    family = OllamaVoice("gemma3", opener=FakeAPI(models=["gemma3:1b"]))
    assert family.health().model_present is True

    other = OllamaVoice("gemma3:4b", opener=FakeAPI(models=["gemma3:1b"]))
    assert other.health().model_present is False

    down = OllamaVoice("gemma3:1b", opener=lambda request, timeout=None: (_ for _ in ()).throw(TimeoutError()))
    assert down.health().reachable is False
