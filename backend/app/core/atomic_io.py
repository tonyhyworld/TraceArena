"""Small same-filesystem atomic writers for audit-critical artifacts."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Union


def atomic_write_text(
    path: Union[str, Path], content: str, *, encoding: str = "utf-8",
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent),
    )
    try:
        with os.fdopen(descriptor, "w", encoding=encoding) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return target
