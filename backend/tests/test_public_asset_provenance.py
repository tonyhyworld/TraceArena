"""Public candidate asset provenance must remain complete and content-bound."""
import hashlib
from pathlib import Path

import yaml


ASSETS = Path(__file__).parents[1] / "scenarios" / "capital_market" / "assets"


def test_public_capital_market_assets_have_redistribution_provenance():
    manifest = yaml.safe_load((ASSETS / "manifest.yaml").read_text(encoding="utf-8"))
    entries = [
        item
        for group in (manifest.get("assets") or {}).values()
        for item in group
    ]
    assert entries
    for item in entries:
        assert item.get("source")
        assert item.get("author")
        assert item.get("license")
        expected = str(item.get("sha256") or "")
        assert len(expected) == 64
        path = ASSETS.parent / str(item["path"])
        assert path.is_file(), path
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
