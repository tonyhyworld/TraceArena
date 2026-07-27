"""Credential redaction for operational prompts, responses and traces."""
from __future__ import annotations

import re
from typing import Any


_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9_.-]{16,}", re.IGNORECASE),
    re.compile(
        r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."
        r"[A-Za-z0-9_-]{10,}"
    ),
    re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?token|password|secret)\b"
        r"(\s*[:=]\s*)([^\s,;\"']{8,})"
    ),
)
_SECRET_KEYS = {
    "api_key", "apikey", "api_key_override", "access_token", "token",
    "refresh_token", "session_token", "password", "passwd", "secret",
    "client_secret", "private_key", "authorization", "proxy_authorization",
    "x-api-key", "cookie", "set-cookie",
}


def redact_credentials(text: str) -> str:
    """Remove common credential values while preserving useful log context."""
    value = str(text or "")
    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 3:
            value = pattern.sub(r"\1\2[REDACTED]", value)
        else:
            value = pattern.sub("[REDACTED]", value)
    return value


def redact_structure(value: Any) -> Any:
    """Recursively sanitize an operational payload without dropping its shape."""
    if isinstance(value, str):
        return redact_credentials(value)
    if isinstance(value, list):
        return [redact_structure(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_structure(item) for item in value)
    if isinstance(value, dict):
        return {
            key: (
                "[REDACTED]"
                if str(key).strip().lower() in _SECRET_KEYS
                else redact_structure(item)
            )
            for key, item in value.items()
        }
    return value
