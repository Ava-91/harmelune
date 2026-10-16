from __future__ import annotations

import json
import os
import subprocess
import sys
import wave
from pathlib import Path

from harmelune.sidecar import PROTOCOL_VERSION


def write_wav(path: Path, frames: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8000)
        stream.writeframes((b"\x01\x00" if frames % 2 else b"\x00\x00") * frames)


def request(request_id: str, command: str, params: dict | None = None, version: int = PROTOCOL_VERSION) -> str:
    return json.dumps({"version": version, "id": request_id, "command": command, "params": params or {}})


def run_sidecar(input_lines: list[str], config_dir: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(config_dir)
    return subprocess.run(
        [sys.executable, "-m", "harmelune.sidecar"],
        input="\n".join(input_lines) + "\n",
        text=True,
        capture_output=True,
        env=env,
        timeout=30,
        check=False,
    )


def parse_output(stdout: str) -> list[dict]:
    return [json.loads(line) for line in stdout.splitlines() if line.strip()]


def test_protocol_hello_and_shutdown_are_clean(tmp_path: Path):
    completed = run_sidecar([
        request("hello-1", "hello"),
        request("stop-1", "shutdown"),
    ], tmp_path / "config")

    assert completed.returncode == 0
    messages = parse_output(completed.stdout)
    assert [message["type"] for message in messages] == ["result", "result"]
    assert messages[0]["result"]["protocol_version"] == PROTOCOL_VERSION
    assert messages[1]["result"]["stopped"] is True
    assert completed.stderr == ""


def test_protocol_rejects_bad_json_versions_and_unknown_commands(tmp_path: Path):
    completed = run_sidecar([
        "{not-json",
        request("old-version", "hello", version=999),
        request("unknown", "run_shell", {"command": "anything"}),
        request("stop", "shutdown"),
    ], tmp_path / "config")

    messages = parse_output(completed.stdout)
    assert completed.returncode == 0
    assert [message["error"]["code"] for message in messages[:3]] == [
        "INVALID_JSON", "UNSUPPORTED_VERSION", "UNKNOWN_COMMAND"
    ]
    assert all(message["ok"] is False for message in messages[:3])


def test_scan_progress_and_paged_rows_use_only_temp_synthetic_audio(tmp_path: Path):
    a, b = tmp_path / "Library A", tmp_path / "Library B"
    a.mkdir()
    b.mkdir()
    write_wav(a / "Only A.wav", 80)
    write_wav(b / "Only B.wav", 83)
    completed = run_sidecar([
        request("scan-1", "scan", {"library_a": str(a), "library_b": str(b)}),
        request("stop-1", "shutdown"),
    ], tmp_path / "config")

    assert completed.returncode == 0
    messages = parse_output(completed.stdout)
    progress = [message for message in messages if message["type"] == "progress"]
    scan = next(message for message in messages if message.get("id") == "scan-1" and message["type"] == "result")
    assert progress
    assert {message["side"] for message in progress} == {"a", "b"}
    assert scan["result"]["summary"]["tracks_a"] == 1
    assert scan["result"]["summary"]["tracks_b"] == 1
    assert scan["result"]["page"]["total"] == 2
    assert not scan["result"]["summary"]["errors_a"]
    assert not scan["result"]["summary"]["errors_b"]


def test_list_tracks_rejects_unknown_scan_id(tmp_path: Path):
    completed = run_sidecar([
        request("page-1", "list_tracks", {"plan_id": "not-a-real-plan"}),
        request("stop-1", "shutdown"),
    ], tmp_path / "config")
    messages = parse_output(completed.stdout)
    assert messages[0]["type"] == "error"
    assert messages[0]["error"]["code"] == "PLAN_NOT_FOUND"
