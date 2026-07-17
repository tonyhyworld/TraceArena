import asyncio
import json

from app.providers.replay import ReplayProvider


def test_replay_provider_returns_scripted_actions_in_order_without_network():
    provider = ReplayProvider(actions=[
        {"action_id": "wait_and_review", "parameters": {"tick": 1}},
        {
            "action_id": "buy_asset",
            "parameters": {"asset_id": "600036.SH", "quantity": 2},
            "evidence_refs": ["quote_1"],
        },
    ])

    first = json.loads(asyncio.run(provider.complete("", "")))
    second = json.loads(asyncio.run(provider.complete("", "")))
    third = json.loads(asyncio.run(provider.complete("", "")))

    assert provider.provider_name == "replay"
    assert provider.cursor == 3
    assert first["action_id"] == "wait_and_review"
    assert second["action_id"] == "buy_asset"
    assert second["evidence_refs"] == ["quote_1"]
    assert third["action_id"] == "wait_and_review"


def test_replay_provider_deep_copies_scripted_payloads():
    actions = [{"action_id": "wait_and_review", "parameters": {"x": 1}}]
    provider = ReplayProvider(actions=actions)
    actions[0]["parameters"]["x"] = 99

    payload = json.loads(asyncio.run(provider.complete("", "")))

    assert payload["parameters"]["x"] == 1
