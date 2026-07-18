from app.config import AgentSlotConfig
from app.providers.openai_compat import OpenAICompatProvider
from app.providers.registry import build_provider


def test_huggingface_provider_uses_router_defaults(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "test-token")
    cfg = AgentSlotConfig(
        id="agent_a",
        name="Agent A",
        provider="huggingface",
        model="deepseek-ai/DeepSeek-R1:fastest",
    )

    provider = build_provider(cfg)

    assert isinstance(provider, OpenAICompatProvider)
    assert provider.provider_name == "huggingface"
    assert provider.model_name == "deepseek-ai/DeepSeek-R1:fastest"
    assert provider._base_url == "https://router.huggingface.co/v1"
    assert provider._api_key == "test-token"


def test_huggingface_provider_allows_endpoint_override(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "test-token")
    cfg = AgentSlotConfig(
        id="agent_a",
        name="Agent A",
        provider="huggingface",
        model="org/model",
        extra={"base_url": "http://localhost:8000/v1"},
    )

    provider = build_provider(cfg)

    assert provider._base_url == "http://localhost:8000/v1"
