import sys
from types import SimpleNamespace

import pytest

from app.contracts.world_adapter import (
    WorldAdapterActionReceipt,
    WorldAdapterProvenance,
    WorldModelAssurance,
)
from app.core.interfaces import ActionPack
from app.engine.evaluation.spi import ScenarioExecutionRouter
from app.engine.world_adapter import (
    get_world_adapter_descriptor,
    list_world_adapters,
)
from app.engine.world_adapter.grid2op_adapter import Grid2OpAdapter
from app.engine.world_state.kernel import WorldState


COUNTER_ID = "builtin:deterministic_counter"


def _runtime(*, terminal_value=10):
    runtime = SimpleNamespace(
        settlement_cfg={
            "execution": {
                "default": {
                    "mode": "simulation",
                    "provider_id": "counter_authority",
                    "world_adapter_id": COUNTER_ID,
                }
            }
        },
        world_adapter_cfg={
            "adapter_id": COUNTER_ID,
            "model_kind": "algorithmic",
            "seed": 7,
            "config": {
                "initial_value": 0,
                "terminal_value": terminal_value,
            },
        },
        agent_slot_ids=["agent_a", "agent_b"],
        seed_manager=SimpleNamespace(seed=99),
        tools_cfg=[],
        metrics_cfg={},
        get_action_rule=lambda action_id: {"id": action_id},
    )
    return runtime


def test_builtin_adapters_are_explicitly_registered():
    assert COUNTER_ID in list_world_adapters()
    assert "builtin:grid2op" in list_world_adapters()
    assert get_world_adapter_descriptor(COUNTER_ID).model_kind == "algorithmic"
    assert (
        get_world_adapter_descriptor("builtin:grid2op").model_kind
        == "simulator"
    )


def test_failed_receipt_requires_reason():
    with pytest.raises(ValueError, match="requires reasons"):
        WorldAdapterActionReceipt(
            receipt_id="receipt_1",
            command_id="command_1",
            world_tick=1,
            actor_id="agent_a",
            action_type="increment",
            status="failed",
        )


def test_learned_world_model_requires_identity_and_limitations():
    base = {
        "adapter_id": "example:learned",
        "adapter_version": "1",
        "model_kind": "learned",
        "engine_name": "world-agent",
        "config_hash": "abc",
        "source_uri": "model://world-agent",
    }
    with pytest.raises(ValueError, match="model_id"):
        WorldAdapterProvenance(**base)

    provenance = WorldAdapterProvenance(
        **base,
        metadata={"model_id": "domain/world-agent", "model_version": "7"},
        assurance=WorldModelAssurance(
            trust_tier="validated",
            validation_refs=["benchmark://domain-holdout-v2"],
            limitations=["not calibrated for emergency control"],
        ),
    )
    assert provenance.model_kind == "learned"


@pytest.mark.asyncio
async def test_adapter_executes_all_agents_in_one_transition():
    router = ScenarioExecutionRouter(_runtime())
    router.initialize()
    state = WorldState(["agent_a", "agent_b"])
    router.bind_state(state)
    actions = [
        ActionPack(
            agent_id="agent_a",
            action_id="increment",
            parameters={"amount": 3},
        ),
        ActionPack(
            agent_id="agent_b",
            action_id="increment",
            parameters={"amount": 5},
        ),
    ]

    results = await router.run_action_batch(actions, 1, state, {})

    assert set(results) == {"agent_a", "agent_b"}
    assert {
        item.world_transition.transition_id for item in results.values()
    } == {"counter-transition:1"}
    assert results["agent_a"].world_action_receipt.status == "executed"
    assert results["agent_b"].world_action_receipt.status == "executed"
    assert state.internal["world_adapter"]["snapshot"]["values"] == {
        "agent_a": 3.0,
        "agent_b": 5.0,
    }
    assert state.internal["world_adapter"]["provenance"]["seed"] == 7
    assert (
        state.internal["world_adapter"]["provenance"]["model_kind"]
        == "algorithmic"
    )


@pytest.mark.asyncio
async def test_hybrid_settlement_route_can_use_same_world_adapter_boundary():
    runtime = _runtime()
    runtime.settlement_cfg["execution"]["default"]["mode"] = "hybrid"
    router = ScenarioExecutionRouter(runtime)
    router.initialize()
    state = WorldState(["agent_a", "agent_b"])
    router.bind_state(state)

    results = await router.run_action_batch([
        ActionPack(
            agent_id="agent_a",
            action_id="increment",
            parameters={"amount": 2},
        )
    ], 1, state, {})

    assert results["agent_a"].world_action_receipt.status == "executed"
    assert router.execution_route("increment")["mode"] == "hybrid"
    assert router.requires_simulation("increment") is True


def test_adapter_rejects_declared_world_model_kind_mismatch():
    runtime = _runtime()
    runtime.world_adapter_cfg["model_kind"] = "learned"
    router = ScenarioExecutionRouter(runtime)

    with pytest.raises(ValueError, match="world model kind mismatch"):
        router.initialize()


@pytest.mark.asyncio
async def test_adapter_rejects_unknown_action_without_inventing_effect():
    router = ScenarioExecutionRouter(_runtime())
    router.initialize()
    state = WorldState(["agent_a", "agent_b"])
    router.bind_state(state)
    action = ActionPack(agent_id="agent_a", action_id="teleport")

    results = await router.run_action_batch([action], 1, state, {})

    result = results["agent_a"]
    assert result.outcome == "invalid"
    assert result.world_action_receipt.status == "rejected"
    assert result.world_action_receipt.reasons == ["unsupported_action"]
    assert state.internal["world_adapter"]["snapshot"]["values"]["agent_a"] == 0.0


@pytest.mark.asyncio
async def test_adapter_terminal_state_updates_os_world_state():
    router = ScenarioExecutionRouter(_runtime(terminal_value=2))
    router.initialize()
    state = WorldState(["agent_a", "agent_b"])
    router.bind_state(state)

    await router.run_action_batch([
        ActionPack(
            agent_id="agent_a",
            action_id="increment",
            parameters={"amount": 2},
        )
    ], 1, state, {})

    assert state.is_game_over
    assert state.winner_id == "agent_a"
    assert state.internal["world_adapter"]["terminal"]["reason"] == "target_reached"


def test_grid2op_adapter_forks_same_seed_for_every_actor(monkeypatch):
    created = []

    class FakeObservation:
        current_step = 0
        rho = [0.2, 0.4]
        line_status = [True, True]
        gen_p = [10.0]
        load_p = [9.0]

    class FakeEnv:
        def __init__(self):
            self.seeds = []
            self.action_space = lambda payload: dict(payload)

        def seed(self, value):
            self.seeds.append(value)

        def reset(self):
            return FakeObservation()

        def step(self, action):
            return FakeObservation(), 1.5, False, {"action": action}

        def close(self):
            return None

    def make(_name, **_kwargs):
        env = FakeEnv()
        created.append(env)
        return env

    monkeypatch.setitem(
        sys.modules,
        "grid2op",
        SimpleNamespace(make=make, __version__="test"),
    )
    adapter = Grid2OpAdapter()
    adapter.initialize({
        "actor_ids": ["agent_a", "agent_b"],
        "environment": "fake_grid",
        "action_mapping": {"redispatch": {"redispatch": [(0, 1.0)]}},
    }, seed=42)
    adapter.reset()

    submitted = adapter.apply_actions([
        SimpleNamespace(
            command_id="cmd_a",
            world_tick=1,
            actor_id="agent_a",
            action_type="redispatch",
            parameters={},
        ),
        SimpleNamespace(
            command_id="cmd_b",
            world_tick=1,
            actor_id="agent_b",
            action_type="redispatch",
            parameters={},
        ),
    ])
    transition = adapter.step(1)

    assert len(created) == 2
    assert [env.seeds for env in created] == [[42], [42]]
    assert [item.status for item in submitted] == ["accepted", "accepted"]
    assert [item.status for item in transition.receipts] == ["executed", "executed"]
    assert transition.metrics["agent_a"]["cumulative_reward"] == 1.5
    assert transition.provenance.metadata["isolated_environment_per_actor"]
