from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class AgentRoleKey(str, Enum):
    STRATEGY = "strategy"
    SCRIPT = "script"
    VISUAL = "visual"
    EDITOR = "editor"
    OPS = "ops"


class LLMConfig(BaseModel):
    provider: Literal["openai", "anthropic", "deepseek", "grsai"] = "grsai"
    model: str = "gpt-5.4"
    base_url: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096


LLM_PROVIDER_CATALOG: list[dict[str, str]] = [
    {
        "id": "grsai",
        "name": "Grsai",
        "base_url": "https://grsai.dakka.com.cn/v1",
        "default_model": "gpt-5.4",
        "docs": "https://grsai.ai/zh/dashboard/api-keys",
        "note": "OpenAI 兼容；全球节点 https://grsaiapi.com/v1",
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o",
        "docs": "https://platform.openai.com/",
        "note": "",
    },
    {
        "id": "anthropic",
        "name": "Anthropic",
        "base_url": "https://api.anthropic.com",
        "default_model": "claude-3-5-sonnet-20241022",
        "docs": "https://docs.anthropic.com/",
        "note": "",
    },
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-chat",
        "docs": "https://platform.deepseek.com/",
        "note": "",
    },
]


class ToolCapability(BaseModel):
    key: str
    name: str
    description: str = ""
    enabled: bool = True


class PromptSkill(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    content: str
    enabled: bool = True
    source: Literal["manual", "upload", "url", "feishu"] = "manual"
    origin: str = ""
    description: str = ""


class McpServerConfig(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    transport: Literal["sse", "stdio", "http"] = "http"
    url: str = ""
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    description: str = ""


class AgentProfile(BaseModel):
    role: AgentRoleKey
    title: str
    identity: str = ""
    personality: str = ""
    craft: str = ""
    work_style: str = ""
    memory: str = ""
    capability_boundary: str = ""
    system_prompt: str = ""
    llm: LLMConfig = Field(default_factory=LLMConfig)
    tools: list[ToolCapability] = Field(default_factory=list)
    skills: list[PromptSkill] = Field(default_factory=list)
    mcp_servers: list[McpServerConfig] = Field(default_factory=list)
    enabled: bool = True
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def composed_system_prompt(self) -> str:
        from matrixsolo.admin.personas import COLLEAGUES, STUDIO_VOICE

        parts = [
            "## 活人感守则\n" + STUDIO_VOICE.strip(),
            "## 工作室共识\n" + COLLEAGUES.strip(),
        ]
        if self.identity.strip():
            parts.append(f"## 身份设定\n{self.identity.strip()}")
        if self.personality.strip():
            parts.append(f"## 专属性格\n{self.personality.strip()}")
        if self.craft.strip():
            parts.append(f"## 专属职业能力\n{self.craft.strip()}")
        if self.work_style.strip():
            parts.append(f"## 专属做事风格\n{self.work_style.strip()}")
        if self.memory.strip():
            parts.append(f"## 专属记忆\n{self.memory.strip()}")
        if self.capability_boundary.strip():
            parts.append(f"## 能力边界\n{self.capability_boundary.strip()}")
        if self.system_prompt.strip():
            parts.append(f"## 任务契约\n{self.system_prompt.strip()}")
        enabled_tools = [t for t in self.tools if t.enabled]
        if enabled_tools:
            tool_lines = "\n".join(f"- {t.key}：{t.description or t.name}" for t in enabled_tools)
            parts.append(
                "## 已启用内置技能\n"
                f"{tool_lines}\n"
                "热榜/选题必须自己用 hot_radar 或 web_fetch，禁止问老板要片名，也不要把爬虫甩给运营。"
            )
        enabled_skills = [s for s in self.skills if s.enabled and s.content.strip()]
        if enabled_skills:
            skill_block = "\n\n".join(
                f"### Skill: {s.name}\n{s.content.strip()}" for s in enabled_skills
            )
            parts.append(f"## 已启用 Skills\n{skill_block}")
        enabled_mcp = [m for m in self.mcp_servers if m.enabled]
        if enabled_mcp:
            mcp_lines = "\n".join(
                f"- {m.name} ({m.transport}) {m.url or m.command}" for m in enabled_mcp
            )
            parts.append(f"## 已接入 MCP\n{mcp_lines}")
        return "\n\n".join(p for p in parts if p)

    def has_tool(self, key: str) -> bool:
        for t in self.tools:
            if t.key == key:
                return t.enabled
        return False

    def dump_admin(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["composed_system_prompt"] = self.composed_system_prompt()
        return data


class AgentProfilePatch(BaseModel):
    title: str | None = None
    identity: str | None = None
    personality: str | None = None
    craft: str | None = None
    work_style: str | None = None
    memory: str | None = None
    capability_boundary: str | None = None
    system_prompt: str | None = None
    llm: LLMConfig | None = None
    tools: list[ToolCapability] | None = None
    skills: list[PromptSkill] | None = None
    mcp_servers: list[McpServerConfig] | None = None
    enabled: bool | None = None


class PromptSkillCreate(BaseModel):
    name: str
    content: str
    enabled: bool = True
    source: Literal["manual", "upload", "url", "feishu"] = "manual"
    origin: str = ""
    description: str = ""


class PromptSkillUpdate(BaseModel):
    name: str | None = None
    content: str | None = None
    enabled: bool | None = None


class McpServerCreate(BaseModel):
    name: str
    transport: Literal["sse", "stdio", "http"] = "http"
    url: str = ""
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    description: str = ""


class McpServerUpdate(BaseModel):
    name: str | None = None
    transport: Literal["sse", "stdio", "http"] | None = None
    url: str | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    enabled: bool | None = None
    description: str | None = None


TOOL_CATALOG: list[dict[str, str]] = [
    {"key": "web_fetch", "name": "联网抓取", "description": "GET 打开公开网页/API 并抽取正文"},
    {"key": "browser_crawl", "name": "基础爬虫", "description": "浏览器 UA 爬取公开页，可一次多个 URL"},
    {"key": "hot_radar", "name": "热榜雷达", "description": "拉取抖音/微博/B站/猫眼/豆瓣热榜"},
    {"key": "rag", "name": "RAG 检索", "description": "检索爆款文案与事实库"},
    {"key": "safety", "name": "合规三层过滤", "description": "敏感词/Guardrail/事实核查"},
    {"key": "cover_gen", "name": "封面生成", "description": "封面方向；与 image_gen 一起可真实出图"},
    {"key": "image_gen", "name": "Grsai 生图", "description": "调用 gpt-image-2 真实出图并回传到飞书"},
    {"key": "tts", "name": "TTS 配音", "description": "Edge/Azure 语音合成"},
    {"key": "subtitle", "name": "字幕轴", "description": "ASS 字幕生成"},
    {"key": "mcp_edit", "name": "MCP 剪辑渲染", "description": "本地自动剪辑/导出"},
    {"key": "distribute", "name": "多平台分发封装", "description": "抖音/B站/头条元数据与排期"},
    {"key": "feishu_hitl", "name": "飞书 HITL 卡片", "description": "以本岗身份发送审批卡片"},
    {"key": "bitable", "name": "多维表格写入", "description": "任务/日历看板同步"},
    {"key": "mcp_tools", "name": "外部 MCP 工具", "description": "调用本岗已启用的 MCP Server 工具"},
]
