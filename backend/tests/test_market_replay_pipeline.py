"""Deterministic, no-key proof that replay actions use the formal EngineOS path."""
import asyncio
from pathlib import Path

import pytest

from app.config import AgentSlotConfig, FrameworkConfig
from app.engine.main import EngineOS
from app.engine.scenario_boot.loader import ScenarioBootKernel


CAPITAL_SCENARIO = Path(__file__).parents[1] / "scenarios" / "capital_market"


@pytest.fixture(autouse=True)
def _restore_default_event_loop():
    """Keep sync tests that construct asyncio.Lock compatible after pytest-asyncio."""
    yield
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if loop.is_closed():
        asyncio.set_event_loop(asyncio.new_event_loop())


def _observation(run_id, agent_id, asset_id, categories, *, price=None):
    value = {
        "asset_id": asset_id,
        "symbol": asset_id,
        "research_categories": list(categories),
        "source_uri": f"fixture://market-replay/{run_id}",
    }
    if price is not None:
        value["price"] = price
    return {
        "run_id": run_id,
        "ok": True,
        "source": "verified_external",
        "owner_id": agent_id,
        "outputs": [value],
    }


def _script(agent_id, research):
    asset = "600036.SH"
    refs = [item["run_id"] for item in research]
    return [
        {
            "action_id": "wait_and_review",
            "action_name": "Replay research",
            "plan": "读取固定 fixture 证据，等待下一拍执行预先定义的决策。",
            "public_reasoning_summary": "先完成可审计研究，再按固定回放路径行动。",
            "character_monologue": "我先核对证据，再决定是否出手。",
            "evidence_refs": refs,
            "parameters": {"harness_observations": research},
        },
        {
            "action_id": "buy_asset" if agent_id == "investor_a" else "wait_and_review",
            "action_name": "Replay decision",
            "plan": "仅按 fixture 中已经验证的证据执行固定动作。",
            "public_reasoning_summary": "证据链完整，按回放规则执行并控制交易规模。",
            "character_monologue": "我只执行已经记录并核验过的动作。",
            "evidence_refs": refs,
            "target_object_id": "portfolio_book",
            "parameters": {
                "asset_id": asset,
                "quantity": 2,
                "price_evidence_ref": "quote_a_t1" if agent_id == "investor_a" else "quote_b_t1",
            } if agent_id == "investor_a" else {},
        },
    ]


@pytest.mark.asyncio
async def test_market_replay_uses_engine_action_event_settlement_ledger_chain(tmp_path):
    scenario = ScenarioBootKernel.load(str(CAPITAL_SCENARIO))
    scenario.audit_cfg["tick_limit"] = 2
    scenario.settlement_cfg["research_requirements"]["enabled"] = True
    scenario.settlement_cfg["trading_universe"] = {"allowed_markets": ["SH", "SZ", "HK"]}

    agent_a_research = [
        _observation("quote_a_t1", "investor_a", "600036.SH", ["quote"], price=100.0),
        _observation("financials_a_t1", "investor_a", "600036.SH", ["financials"]),
        _observation("valuation_a_t1", "investor_a", "600036.SH", ["valuation"]),
    ]
    agent_b_research = [
        _observation("quote_b_t1", "investor_b", "600036.SH", ["quote"], price=100.0),
        _observation("catalyst_b_t1", "investor_b", "600036.SH", ["catalyst"]),
        _observation("fund_flow_b_t1", "investor_b", "600036.SH", ["fund_flow"]),
    ]
    cfg = FrameworkConfig(
        scenario_path=str(CAPITAL_SCENARIO),
        runtime_mode="replay",
        agents=[
            AgentSlotConfig(
                id="investor_a", name="Replay A", provider="replay", model="replay-v1",
                extra={"actions": _script("investor_a", agent_a_research)},
            ),
            AgentSlotConfig(
                id="investor_b", name="Replay B", provider="replay", model="replay-v1",
                extra={"actions": _script("investor_b", agent_b_research)},
            ),
        ],
        director={"enabled": False, "provider": "mock", "model": "mock-v1"},
        judge={"enabled": False},
        sandbox={"enabled": False},
        mcp={"enabled": False},
        tts={"enabled": False},
        agent_loop={"enabled": False},
        headless=True,
        provider_health_check=False,
        log_dir=str(tmp_path / "runs"),
    )
    engine = EngineOS(cfg, scenario)
    await engine.initialize()

    await engine.step()
    await engine.step()

    actions = engine._last_os2_actions
    observations = engine._os2_observations.all()
    settlements = engine._last_os2_settlements
    assert any(item.action_type == "buy_asset" for item in actions)
    assert {item.observation_id for item in observations} >= {
        "quote_a_t1", "financials_a_t1", "valuation_a_t1",
    }
    filled = [item for item in settlements if item.outcome == "portfolio_marked_to_market"]
    assert filled
    a_record = next(item for item in filled if "investor_a" in item.subject_ids)
    assert a_record.values["cash"] == 800.0
    assert a_record.values["portfolio_value"] == 1000.0
    assert any(item.source_event_refs for item in settlements)
    assert engine._trace.run_id
