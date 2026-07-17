from pathlib import Path

from app.engine.scenario_boot.loader import ScenarioBootKernel


SCENARIO = Path(__file__).parents[1] / "scenarios" / "capital_market"


def test_capital_market_english_locale_overlays_presentation_only():
    scenario = ScenarioBootKernel.load(str(SCENARIO), locale="en-US")
    assert scenario.locale == "en-US"
    assert scenario.manifest.name == "Capital Market Investment Simulation v0"
    assert scenario.agent_roles[0].display_name == "Chen Wen"
    assert scenario.presentation.ui_text["notice_label"] == "Market brief"
    assert next(item for item in scenario.actions_cfg if item["id"] == "buy_asset")["name"] == "Buy / open position"
    assert scenario.settlement_cfg["providers"][0]["id"] == "portfolio_order_validator"
