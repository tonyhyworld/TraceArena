from pathlib import Path

from app.contracts.round_model import load_round_model
from app.engine.evaluation.settlement import load_scenario_settlement_plugin
from app.engine.scenario_boot.compiler import ScenarioCompiler
from app.engine.scenario_boot.loader import ScenarioBootKernel


SCENARIO = Path(__file__).resolve().parents[1] / "scenarios" / "capital_market_us"


def test_capital_market_us_scenario_compiles_with_us_contract() -> None:
    scenario = ScenarioBootKernel.load(str(SCENARIO))
    compiled = ScenarioCompiler.compile(scenario)

    assert scenario.manifest.scenario_id == "capital_market_us_dual_agent_v1"
    assert len(compiled.role_index) == 2
    assert set(compiled.action_index) >= {
        "update_investment_plan",
        "buy_asset",
        "sell_asset",
        "wait_and_review",
    }
    assert set(compiled.tool_index) >= {
        "us_quote",
        "us_sec_filings",
        "us_financial_statements",
        "us_valuation_metrics",
    }
    assert compiled.tool_index["us_quote"]["mcp_server"] == "longport"
    assert compiled.tool_index["us_quote"]["mcp_tool"] == "longport_quote"
    assert (
        compiled.tool_index["us_sec_filings"]["mcp_server"]
        == "us_market_research"
    )
    assert (
        compiled.tool_index["us_financial_statements"]["mcp_tool"]
        == "us_financial_statements"
    )
    assert (
        compiled.tool_index["us_options_chain"]["mcp_tool"]
        == "longport_option_chain"
    )
    assert all(
        tool.get("mcp_tool") != "public_json_get"
        for tool in compiled.tool_index.values()
    )


def test_capital_market_us_settlement_and_clock_are_scenario_owned() -> None:
    scenario = ScenarioBootKernel.load(str(SCENARIO))
    settlement = scenario.settlement_cfg
    clock = load_round_model(SCENARIO)

    assert settlement["trading_universe"]["allowed_markets"] == ["US"]
    assert settlement["portfolio_ledger"]["currency"] == "USD"
    assert settlement["portfolio_ledger"]["initial_cash"] == 10000
    assert settlement["benchmark"]["id"] == "SPY.US"
    assert clock.live_window.timezone == "America/New_York"
    assert list(clock.live_window.ranges) == ["09:30-16:00"]

    plugins = load_scenario_settlement_plugin(SCENARIO)
    assert [plugin.plugin_id for plugin in plugins] == [
        "capital_market_us.portfolio.v1"
    ]
