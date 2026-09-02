from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _blank_external_keys(monkeypatch):
    """测试必须封闭：清空 LLM / 飞书密钥，避免命中真实网络或真实凭证."""
    for key in (
        "GRSAI_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "DEEPSEEK_API_KEY",
        "FEISHU_APP_ID",
        "FEISHU_APP_SECRET",
        "FEISHU_STRATEGY_APP_ID",
        "FEISHU_STRATEGY_APP_SECRET",
    ):
        monkeypatch.setenv(key, "")
    # 进入测试后 Settings 缓存必须失效，让上面的空值生效
    from matrixsolo.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
