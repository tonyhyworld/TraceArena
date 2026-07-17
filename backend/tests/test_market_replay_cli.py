import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "backend/scripts/market_replay.py"
FIXTURE = ROOT / "examples/market_replay/fixture.json"


def test_market_replay_cli_is_no_key_and_exports_authoritative_replay(tmp_path):
    output = tmp_path / "replay"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "backend")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--fixture", str(FIXTURE),
            "--output", str(output),
        ],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "brokerage: disabled" in result.stdout
    assert "network: disabled" in result.stdout

    manifest = json.loads((output / "run_manifest.json").read_text())
    replay = json.loads((output / "replay_deterministic.json").read_text())
    assert manifest["provider"] == "replay"
    assert manifest["brokerage"] == "disabled"
    assert manifest["network"] == "disabled"
    assert len(replay["ticks"]) == 2
    terminal = replay["ticks"][-1]["settlements"]
    investor_a = next(item for item in terminal if "investor_a" in item["subject_ids"])
    assert investor_a["outcome"] == "portfolio_marked_to_market"
    assert investor_a["values"]["cash"] == 800.0


def test_market_replay_cli_completes_when_socket_connections_are_blocked(tmp_path):
    output = tmp_path / "replay"
    guard = tmp_path / "socket_guard"
    guard.mkdir()
    (guard / "sitecustomize.py").write_text(
        "import socket\n"
        "def _blocked(*args, **kwargs):\n"
        "    raise RuntimeError('network connection blocked by replay test')\n"
        "socket.socket.connect = _blocked\n"
        "socket.create_connection = _blocked\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(guard), str(ROOT / "backend")])
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--fixture", str(FIXTURE),
            "--output", str(output),
        ],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "network: disabled" in result.stdout


def test_market_replay_cli_exports_chinese_localized_summary(tmp_path):
    output = tmp_path / "replay"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "backend")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--fixture", str(FIXTURE),
            "--output", str(output),
            "--locale", "zh-CN",
        ],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "TraceArena 市场回放" in result.stdout
    manifest = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["locale"] == "zh-CN"
    assert "不构成投资建议" in (output / "summary.md").read_text(encoding="utf-8")
