"""Executable world adapter SDK and built-in registrations."""
from app.engine.world_adapter.base import WorldAdapter
from app.engine.world_adapter.reference import DeterministicCounterAdapter
from app.engine.world_adapter.grid2op_adapter import Grid2OpAdapter
from app.engine.world_adapter.registry import (
    get_world_adapter_descriptor,
    get_world_adapter_factory,
    list_world_adapters,
    register_world_adapter,
)


def _register_builtins() -> None:
    if DeterministicCounterAdapter.adapter_id not in list_world_adapters():
        register_world_adapter(
            DeterministicCounterAdapter.adapter_id,
            DeterministicCounterAdapter,
            model_kind="algorithmic",
            capabilities=frozenset({"deterministic_replay", "isolated_actors"}),
        )
    if Grid2OpAdapter.adapter_id not in list_world_adapters():
        register_world_adapter(
            Grid2OpAdapter.adapter_id,
            Grid2OpAdapter,
            model_kind="simulator",
            capabilities=frozenset({"seeded_replay", "isolated_actors"}),
        )


_register_builtins()

__all__ = [
    "WorldAdapter",
    "get_world_adapter_descriptor",
    "get_world_adapter_factory",
    "list_world_adapters",
    "register_world_adapter",
]
