from __future__ import annotations

import json
import stat
import zipfile
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.operator_runs import _scenario_label_maps
from app.api.scenario_upload import _safe_extract
from app.auth import crypto
from app.auth.jwt_utils import create_token, decode_token
from app.auth.models import User
from app.core.path_safety import path_beneath, safe_path_component


@pytest.mark.parametrize(
    "value",
    ["../admin", "a/b", "a\\b", "/tmp/admin", ".", "..", " spaced"],
)
def test_safe_path_component_rejects_traversal(value: str) -> None:
    with pytest.raises(ValueError):
        safe_path_component(value)


def test_user_id_is_a_safe_path_component() -> None:
    user = User(user_id="u_123", username="alice")
    assert user.user_id == "u_123"
    with pytest.raises(ValidationError):
        User(user_id="../outside", username="alice")


def test_path_beneath_never_escapes_root(tmp_path: Path) -> None:
    assert path_beneath(tmp_path, "u_123", "secrets.json") == (
        tmp_path / "u_123" / "secrets.json"
    )
    with pytest.raises(ValueError):
        path_beneath(tmp_path, "../outside")


def test_safe_extract_rejects_zip_slip_and_symlinks(tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../outside.txt", "blocked")
    with zipfile.ZipFile(archive) as zf, pytest.raises(HTTPException):
        _safe_extract(zf, tmp_path / "extract")

    symlink_archive = tmp_path / "symlink.zip"
    info = zipfile.ZipInfo("linked")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(symlink_archive, "w") as zf:
        zf.writestr(info, "../../outside")
    with zipfile.ZipFile(symlink_archive) as zf, pytest.raises(HTTPException):
        _safe_extract(zf, tmp_path / "extract-link")


def test_safe_extract_writes_regular_files(tmp_path: Path) -> None:
    archive = tmp_path / "ok.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("manifest.json", "{}")
        zf.writestr("world/rules.yaml", "rules: []")
    destination = tmp_path / "extract"
    destination.mkdir()
    with zipfile.ZipFile(archive) as zf:
        _safe_extract(zf, destination)
    assert (destination / "manifest.json").read_text() == "{}"
    assert (destination / "world" / "rules.yaml").is_file()


def test_archive_labels_do_not_follow_manifest_paths(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    (outside / "world").mkdir(parents=True)
    (outside / "world" / "actions.yaml").write_text(
        "actions:\n  - id: injected\n    name: Injected\n", encoding="utf-8"
    )
    run_dir = tmp_path / "run_safe"
    run_dir.mkdir()
    (run_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "scenario": {"path": str(outside)},
                "terminology": {"action_labels": {"frozen": "Frozen"}},
            }
        ),
        encoding="utf-8",
    )
    action_labels, *_ = _scenario_label_maps(run_dir)
    assert action_labels == {"frozen": "Frozen"}
    assert "injected" not in action_labels


def test_auth_secrets_are_required_and_never_written(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AIWORLD_JWT_SECRET", raising=False)
    user = User(user_id="u_123", username="alice")
    with pytest.raises(RuntimeError):
        create_token(user)

    monkeypatch.setenv("AIWORLD_JWT_SECRET", "j" * 48)
    token = create_token(user)
    assert decode_token(token)["user_id"] == "u_123"

    monkeypatch.delenv("AIWORLD_SECRET_KEY", raising=False)
    monkeypatch.setattr(crypto, "_cipher", None)
    with pytest.raises(RuntimeError):
        crypto.encrypt("provider-secret")

    monkeypatch.setenv("AIWORLD_SECRET_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(crypto, "_cipher", None)
    encrypted = crypto.encrypt("provider-secret")
    assert encrypted != "provider-secret"
    assert crypto.decrypt(encrypted) == "provider-secret"
