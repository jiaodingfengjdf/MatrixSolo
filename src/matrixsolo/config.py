from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = Field(default="0.0.0.0", alias="MATRIXSOLO_HOST")
    port: int = Field(default=9797, alias="MATRIXSOLO_PORT")
    debug: bool = Field(default=True, alias="MATRIXSOLO_DEBUG")
    data_dir: Path = Field(default=Path("./data"), alias="MATRIXSOLO_DATA_DIR")
    assets_dir: Path = Field(default=Path("./Assets"), alias="MATRIXSOLO_ASSETS_DIR")

    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    openai_model: str = Field(default="gpt-4o", alias="OPENAI_MODEL")

    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    anthropic_base_url: str = Field(default="https://api.anthropic.com", alias="ANTHROPIC_BASE_URL")
    anthropic_model: str = Field(
        default="claude-3-5-sonnet-20241022", alias="ANTHROPIC_MODEL"
    )

    deepseek_api_key: str = Field(default="", alias="DEEPSEEK_API_KEY")
    deepseek_base_url: str = Field(default="https://api.deepseek.com", alias="DEEPSEEK_BASE_URL")
    deepseek_model: str = Field(default="deepseek-chat", alias="DEEPSEEK_MODEL")

    # Grsai OpenAI 兼容底座（国内节点默认）
    grsai_api_key: str = Field(default="", alias="GRSAI_API_KEY")
    grsai_base_url: str = Field(
        default="https://grsai.dakka.com.cn/v1", alias="GRSAI_BASE_URL"
    )
    grsai_model: str = Field(default="gpt-5.4", alias="GRSAI_MODEL")

    llm_default_provider: str = Field(default="grsai", alias="LLM_DEFAULT_PROVIDER")

    feishu_app_id: str = Field(default="", alias="FEISHU_APP_ID")
    feishu_app_secret: str = Field(default="", alias="FEISHU_APP_SECRET")
    # 五岗 AI 员工（优先于通用 FEISHU_APP_*）
    feishu_strategy_app_id: str = Field(default="", alias="FEISHU_STRATEGY_APP_ID")
    feishu_strategy_app_secret: str = Field(default="", alias="FEISHU_STRATEGY_APP_SECRET")
    feishu_script_app_id: str = Field(default="", alias="FEISHU_SCRIPT_APP_ID")
    feishu_script_app_secret: str = Field(default="", alias="FEISHU_SCRIPT_APP_SECRET")
    feishu_visual_app_id: str = Field(default="", alias="FEISHU_VISUAL_APP_ID")
    feishu_visual_app_secret: str = Field(default="", alias="FEISHU_VISUAL_APP_SECRET")
    feishu_editor_app_id: str = Field(default="", alias="FEISHU_EDITOR_APP_ID")
    feishu_editor_app_secret: str = Field(default="", alias="FEISHU_EDITOR_APP_SECRET")
    feishu_ops_app_id: str = Field(default="", alias="FEISHU_OPS_APP_ID")
    feishu_ops_app_secret: str = Field(default="", alias="FEISHU_OPS_APP_SECRET")
    feishu_verification_token: str = Field(default="", alias="FEISHU_VERIFICATION_TOKEN")
    feishu_encrypt_key: str = Field(default="", alias="FEISHU_ENCRYPT_KEY")
    feishu_hitl_chat_id: str = Field(default="", alias="FEISHU_HITL_CHAT_ID")
    feishu_bitable_app_token: str = Field(default="", alias="FEISHU_BITABLE_APP_TOKEN")
    feishu_table_content_calendar: str = Field(default="", alias="FEISHU_TABLE_CONTENT_CALENDAR")
    feishu_table_tasks: str = Field(default="", alias="FEISHU_TABLE_TASKS")
    feishu_table_assets: str = Field(default="", alias="FEISHU_TABLE_ASSETS")
    feishu_table_metrics: str = Field(default="", alias="FEISHU_TABLE_METRICS")
    feishu_table_work_logs: str = Field(default="", alias="FEISHU_TABLE_WORK_LOGS")

    chroma_persist_dir: Path = Field(default=Path("./data/chroma"), alias="CHROMA_PERSIST_DIR")
    chroma_collection: str = Field(default="matrixsolo_rag", alias="CHROMA_COLLECTION")
    chroma_enabled: bool = Field(default=False, alias="CHROMA_ENABLED")

    tts_provider: Literal["edge", "azure"] = Field(default="edge", alias="TTS_PROVIDER")
    azure_speech_key: str = Field(default="", alias="AZURE_SPEECH_KEY")
    azure_speech_region: str = Field(default="", alias="AZURE_SPEECH_REGION")
    edge_tts_voice: str = Field(default="zh-CN-YunxiNeural", alias="EDGE_TTS_VOICE")
    digital_human_mode: Literal["avatar", "slideshow"] = Field(
        default="slideshow", alias="DIGITAL_HUMAN_MODE"
    )

    mcp_host: str = Field(default="127.0.0.1", alias="MCP_HOST")
    mcp_port: int = Field(default=8765, alias="MCP_PORT")
    mcp_workspace: Path = Field(default=Path("./Assets"), alias="MCP_WORKSPACE")

    enable_scheduler: bool = Field(default=True, alias="ENABLE_SCHEDULER")
    enable_feishu_chat: bool = Field(default=True, alias="ENABLE_FEISHU_CHAT")
    hot_radar_cron: str = Field(default="0 8,18 * * *", alias="HOT_RADAR_CRON")
    metrics_sync_cron: str = Field(default="0 0 * * *", alias="METRICS_SYNC_CRON")
    cache_cleanup_cron: str = Field(default="0 3 * * *", alias="CACHE_CLEANUP_CRON")

    def ensure_dirs(self) -> None:
        for path in (
            self.data_dir,
            self.assets_dir,
            self.chroma_persist_dir,
            self.data_dir / "workflows",
            self.data_dir / "cache",
            self.data_dir / "exports",
            self.data_dir / "logs",
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
