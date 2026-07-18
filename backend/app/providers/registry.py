"""
Provider 注册表

新增 Provider = 在 _FACTORIES 里加一行，其余代码不动。
"""
from __future__ import annotations

import os
from typing import Any, Callable, Dict, Optional

# 确保 .env 总是被加载（main.py 启动时也会调用，重复调用无害）
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv()
except ImportError:
    pass

from app.config import AgentSlotConfig
from app.providers.base import LLMProvider
from app.providers.mock import MockProvider
from app.providers.replay import ReplayProvider
from app.providers.openai_compat import make_deepseek, make_openai, OpenAICompatProvider
from app.providers.anthropic import AnthropicProvider


# provider_name → 工厂函数。第二个参数是"已解析好的 API Key"（可能为 None），
# 工厂内部再各自决定要不要退回 os.environ 兜底——不再由 registry 往 os.environ 写。
def _sampling_kwargs(cfg: AgentSlotConfig) -> Dict[str, Any]:
    """从 slot extra 读实例级采样参数（温度按人设差异化 / 决策带宽）。"""
    out: Dict[str, Any] = {}
    if cfg.extra.get("temperature") is not None:
        out["default_temperature"] = float(cfg.extra["temperature"])
    if cfg.extra.get("max_tokens") is not None:
        out["default_max_tokens"] = int(cfg.extra["max_tokens"])
    return out


_FACTORIES: Dict[str, Callable[[AgentSlotConfig, Optional[str]], LLMProvider]] = {
    "mock": lambda cfg, key: MockProvider(
        delay=float(cfg.extra.get("delay", 0.0)),
        seed=cfg.extra.get("seed"),
        model_name=cfg.model or "mock-v1",
    ),
    "replay": lambda cfg, key: ReplayProvider(
        actions=list(cfg.extra.get("actions") or []),
        model_name=cfg.model or "replay-v1",
        delay=float(cfg.extra.get("delay", 0.0)),
    ),
    "deepseek": lambda cfg, key: make_deepseek(
        cfg.model, api_key=key, **_sampling_kwargs(cfg),
    ),
    "openai": lambda cfg, key: make_openai(
        cfg.model, api_key=key, **_sampling_kwargs(cfg),
    ),
    "anthropic": lambda cfg, key: AnthropicProvider(cfg.model, api_key=key),
    # MiniMax 走 OpenAI 兼容接口
    "minimax": lambda cfg, key: OpenAICompatProvider(
        model=cfg.model,
        api_key=key or os.environ.get("MINIMAX_API_KEY"),
        base_url="https://api.minimaxi.com/v1",
        provider_id="minimax",
        **_sampling_kwargs(cfg),
    ),
    # 火山方舟 OpenAI 兼容接口
    "ark": lambda cfg, key: OpenAICompatProvider(
        model=cfg.model,
        api_key=key or os.environ.get("ARK_API_KEY"),
        base_url=str(
            cfg.extra.get("base_url")
            or os.environ.get("ARK_BASE_URL")
            or "https://ark.cn-beijing.volces.com/api/v3"
        ),
        provider_id="ark",
        **_sampling_kwargs(cfg),
    ),
    # Hugging Face Inference Providers 的 OpenAI-compatible Chat Completions API。
    "huggingface": lambda cfg, key: OpenAICompatProvider(
        model=cfg.model,
        api_key=key or os.environ.get("HF_TOKEN"),
        base_url=str(
            cfg.extra.get("base_url")
            or os.environ.get("HF_BASE_URL")
            or "https://router.huggingface.co/v1"
        ),
        provider_id="huggingface",
        **_sampling_kwargs(cfg),
    ),
}

_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "minimax": "MINIMAX_API_KEY",
    "ark": "ARK_API_KEY",
    "huggingface": "HF_TOKEN",
}


def build_provider(cfg: AgentSlotConfig, *, user_id: str = "") -> LLMProvider:
    """根据 AgentSlotConfig 创建对应 Provider，无 Key 时自动降级 Mock。

    API Key 优先级：用户覆盖（cfg.api_key_override）> .env 环境变量。
    driver=agent 时使用 ExternalAgentProvider（外部 WebSocket 驱动）。
    """
    driver = str(getattr(cfg, "driver", "") or cfg.extra.get("driver") or "llm").strip().lower()
    if driver == "agent":
        from app.providers.external_agent import ExternalAgentProvider
        return ExternalAgentProvider(cfg, user_id=user_id)

    factory = _FACTORIES.get(cfg.provider)
    if factory is None:
        raise ValueError(f"未知 Provider: {cfg.provider}，请在 registry.py 注册")

    env_name = _KEY_ENV.get(cfg.provider)
    override_key = getattr(cfg, "api_key_override", None)
    resolved_key = override_key or (os.environ.get(env_name) if env_name else None)

    if env_name and override_key:
        print(f"[registry] ✅ {cfg.provider} 使用用户覆盖 Key")
    elif env_name and not resolved_key:
        print(f"[registry] ⚠️  {cfg.provider} 缺少 {env_name}，降级为 Mock")
        return MockProvider()

    return factory(cfg, resolved_key)
