"""Shared filesystem boundary helpers.

All values that become directory or file-name components must pass through this
module.  Keeping the policy in one place prevents subtly different traversal
checks across API, auth, archive, and agent-workspace code.
"""
from __future__ import annotations

import os
import re
from pathlib import Path


_SAFE_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def safe_path_component(value: object, *, label: str = "path component") -> str:
    """Return one validated, portable path component or raise ``ValueError``."""
    original = str(value or "")
    raw = original.strip()
    normalized = raw.replace("\\", "/")
    leaf = os.path.basename(normalized)
    if (
        not raw
        or raw != original
        or raw != normalized
        or leaf != normalized
        or leaf in {".", ".."}
        or not _SAFE_COMPONENT_RE.fullmatch(leaf)
    ):
        raise ValueError(f"invalid {label}")
    return leaf


def path_beneath(root: Path | str, *components: object) -> Path:
    """Resolve validated components below ``root`` and enforce containment."""
    base = Path(root).resolve()
    safe_parts = [safe_path_component(part) for part in components]
    candidate = base.joinpath(*safe_parts).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise ValueError("path escapes configured root") from exc
    return candidate
