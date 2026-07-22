from pathlib import Path

from app.engine.scenario_boot.loader import ScenarioBootKernel


SCENARIO = Path(__file__).parents[1] / "scenarios" / "capital_market"


def test_capital_market_english_locale_overlays_presentation_text_only():
    scenario = ScenarioBootKernel.load(str(SCENARIO), locale="en-US")

    assert scenario.locale == "en-US"
    assert scenario.manifest.name == "Capital Market Professional Evaluation"
    assert scenario.agent_roles[0].display_name == "Chen Wen"
    assert scenario.presentation.ui_text["notice_label"] == "Market brief"
    assert next(item for item in scenario.actions_cfg if item["id"] == "buy_asset")["name"] == "Buy / open position"
    assert next(item for item in scenario.metrics_cfg["metrics"] if item["id"] == "metric_portfolio_value")["name"] == "Total portfolio value"
    # Semantic identifiers and settlement configuration remain canonical.
    assert scenario.actions_cfg[0]["id"] == "buy_asset"
    assert "portfolio_order_validator" in {
        item["id"] for item in scenario.settlement_cfg["providers"]
    }


def test_canonical_chinese_locale_remains_the_default():
    scenario = ScenarioBootKernel.load(str(SCENARIO))
    assert scenario.locale == "zh-CN"
    assert scenario.manifest.name == "资本市场专业评测"
