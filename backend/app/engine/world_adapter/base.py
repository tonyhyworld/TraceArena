"""The executable-world boundary used by TraceArena."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from app.contracts.world_adapter import (
    WorldAdapterActionReceipt,
    WorldAdapterCommand,
    WorldAdapterObservation,
    WorldAdapterProvenance,
    WorldAdapterTerminal,
    WorldAdapterTransition,
)


@runtime_checkable
class WorldAdapter(Protocol):
    """A pluggable implementation that receives actions and advances a world.

    Implementations may be expert rules, deterministic algorithms, a trained
    world agent, a professional simulator, a real system, or a composition of
    those approaches.  The adapter boundary stays identical for every kind.

    ``apply_actions`` must not advance simulated time.  ``step`` advances the
    environment exactly once for the complete tick, so multiple agents do not
    accidentally move a shared simulator several times in one world tick.
    """

    adapter_id: str
    adapter_version: str

    def initialize(self, config: Dict[str, Any], seed: Optional[int]) -> None: ...

    def reset(self) -> Dict[str, WorldAdapterObservation]: ...

    def observe(self, actor_id: str) -> WorldAdapterObservation: ...

    def legal_actions(self, actor_id: str) -> List[Dict[str, Any]]: ...

    def apply_actions(
        self, commands: List[WorldAdapterCommand]
    ) -> List[WorldAdapterActionReceipt]: ...

    def step(self, world_tick: int) -> WorldAdapterTransition: ...

    def metrics(self) -> Dict[str, Any]: ...

    def terminal(self) -> WorldAdapterTerminal: ...

    def snapshot(self) -> Dict[str, Any]: ...

    def provenance(self) -> WorldAdapterProvenance: ...

    def close(self) -> None: ...
