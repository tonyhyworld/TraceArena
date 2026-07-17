"""Authoritative external observation ledger for AI World OS 2.0."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Optional

from app.contracts.os2 import ExternalObservation


class ObservationRuntime:
    """Normalizes, verifies and stores immutable external observations."""

    def __init__(self) -> None:
        self._records: List[ExternalObservation] = []
        self._index: Dict[str, ExternalObservation] = {}

    @staticmethod
    def content_hash(value: Any) -> str:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    def append(self, observation: ExternalObservation) -> None:
        if observation.observation_id in self._index:
            raise ValueError(
                f"duplicate_external_observation:{observation.observation_id}"
            )
        expected = self.content_hash(observation.raw_value)
        if observation.source_hash != expected:
            raise ValueError(
                f"external_observation_hash_mismatch:{observation.observation_id}"
            )
        frozen = ExternalObservation.model_validate(
            observation.model_dump(mode="python")
        )
        self._records.append(frozen)
        self._index[frozen.observation_id] = frozen

    def extend(self, observations: Iterable[ExternalObservation]) -> None:
        for observation in observations:
            self.append(observation)

    def get(self, observation_id: str) -> Optional[ExternalObservation]:
        return self._index.get(observation_id)

    def all(self) -> List[ExternalObservation]:
        return list(self._records)

    def verified_ids(self) -> set[str]:
        return {
            item.observation_id for item in self._records
            if item.verification_status == "verified"
        }
