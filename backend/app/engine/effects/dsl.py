"""Scene effect DSL validation."""
from __future__ import annotations

from typing import Any, Dict, List


class EffectDSL:
    """Compile-time validator for render/effects.yaml."""

    @staticmethod
    def validate(effects: Dict[str, Any]) -> List[str]:
        errors: List[str] = []
        for effect_id, effect in effects.items():
            effect_type = str(getattr(effect, "type", "") or "")
            if not effect_type:
                errors.append(f"effect {effect_id} 缺少 type")
            duration = getattr(effect, "duration_ms", 0)
            try:
                if int(duration) < 0:
                    errors.append(f"effect {effect_id} duration_ms 不能为负")
            except (TypeError, ValueError):
                errors.append(f"effect {effect_id} duration_ms 非法: {duration}")
        return errors

