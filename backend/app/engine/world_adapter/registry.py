"""Explicit registry for trusted world-model implementations."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, FrozenSet, List

from app.contracts.world_adapter import WorldModelKind
from app.engine.world_adapter.base import WorldAdapter


WorldAdapterFactory = Callable[[], WorldAdapter]


@dataclass(frozen=True)
class WorldAdapterDescriptor:
    adapter_id: str
    model_kind: WorldModelKind
    factory: WorldAdapterFactory
    capabilities: FrozenSet[str] = frozenset()


_WORLD_ADAPTERS: Dict[str, WorldAdapterDescriptor] = {}


def register_world_adapter(
    adapter_id: str,
    factory: WorldAdapterFactory,
    *,
    model_kind: WorldModelKind = "simulator",
    capabilities: FrozenSet[str] = frozenset(),
    replace: bool = False,
) -> None:
    normalized = str(adapter_id or "").strip()
    if not normalized:
        raise ValueError("world adapter id cannot be empty")
    if normalized in _WORLD_ADAPTERS and not replace:
        raise ValueError(f"world adapter already registered: {normalized}")
    _WORLD_ADAPTERS[normalized] = WorldAdapterDescriptor(
        adapter_id=normalized,
        model_kind=model_kind,
        factory=factory,
        capabilities=frozenset(capabilities),
    )


def get_world_adapter_factory(adapter_id: str) -> WorldAdapterFactory:
    normalized = str(adapter_id or "").strip()
    descriptor = _WORLD_ADAPTERS.get(normalized)
    if descriptor is None:
        raise ValueError(
            f"world adapter is not registered: {normalized}; "
            f"available={sorted(_WORLD_ADAPTERS)}"
        )
    return descriptor.factory


def get_world_adapter_descriptor(adapter_id: str) -> WorldAdapterDescriptor:
    normalized = str(adapter_id or "").strip()
    descriptor = _WORLD_ADAPTERS.get(normalized)
    if descriptor is None:
        raise ValueError(
            f"world adapter is not registered: {normalized}; "
            f"available={sorted(_WORLD_ADAPTERS)}"
        )
    return descriptor


def list_world_adapters() -> List[str]:
    return sorted(_WORLD_ADAPTERS)
