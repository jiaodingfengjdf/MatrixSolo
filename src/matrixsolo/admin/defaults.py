from __future__ import annotations

from matrixsolo.admin.models import (
    AgentProfile,
    AgentRoleKey,
    LLMConfig,
    McpServerConfig,
    PromptSkill,
    ToolCapability,
)
from matrixsolo.admin.personas import PERSONAS


def _tools(*keys: str) -> list[ToolCapability]:
    from matrixsolo.admin.models import TOOL_CATALOG

    catalog = {t["key"]: t for t in TOOL_CATALOG}
    out: list[ToolCapability] = []
    for key in keys:
        meta = catalog.get(key, {"key": key, "name": key, "description": ""})
        out.append(
            ToolCapability(
                key=meta["key"],
                name=meta["name"],
                description=meta.get("description", ""),
                enabled=True,
            )
        )
    return out


def _persona(role: AgentRoleKey, **kwargs: object) -> AgentProfile:
    spec = PERSONAS[role.value]
    return AgentProfile(
        role=role,
        identity=spec["identity"],
        personality=spec["personality"],
        craft=spec["craft"],
        work_style=spec["work_style"],
        memory=spec["memory"],
        capability_boundary=spec["capability_boundary"],
        system_prompt=spec["system_prompt"],
        **kwargs,  # type: ignore[arg-type]
    )


def default_profiles() -> dict[str, AgentProfile]:
    profiles = [
        _persona(
            AgentRoleKey.STRATEGY,
            title="总编",
            llm=LLMConfig(
                provider="grsai",
                base_url="https://grsai.dakka.com.cn/v1",
                temperature=0.75,
            ),
            tools=_tools("hot_radar", "web_fetch", "browser_crawl", "rag", "feishu_hitl", "bitable"),
            skills=[
                PromptSkill(
                    name="爆款选题评分口径",
                    content="优先情绪张力与素材丰富度；潜力分加权：0.4*情绪+0.3*受众+0.3*素材，再映射到 0-100。同题头部密度高则降权。",
                )
            ],
        ),
        _persona(
            AgentRoleKey.SCRIPT,
            title="文案",
            llm=LLMConfig(
                provider="grsai",
                base_url="https://grsai.dakka.com.cn/v1",
                temperature=0.85,
            ),
            tools=_tools("web_fetch", "rag", "safety", "feishu_hitl"),
            skills=[
                PromptSkill(
                    name="Hook 三秒法则",
                    content="前三句必须制造认知冲突或悬念，避免剧透结局。先给能念出声的一句，再铺结构。",
                )
            ],
        ),
        _persona(
            AgentRoleKey.VISUAL,
            title="视觉",
            llm=LLMConfig(
                provider="grsai",
                base_url="https://grsai.dakka.com.cn/v1",
                temperature=0.85,
            ),
            tools=_tools("web_fetch", "cover_gen", "image_gen", "feishu_hitl"),
            skills=[
                PromptSkill(
                    name="封面安全区",
                    content="顶部 18% 为标题安全区；人物视线朝向留白侧；大形体强剪影优先于细纹理。",
                )
            ],
        ),
        _persona(
            AgentRoleKey.EDITOR,
            title="剪辑",
            llm=LLMConfig(
                provider="grsai",
                base_url="https://grsai.dakka.com.cn/v1",
                temperature=0.55,
            ),
            tools=_tools("web_fetch", "tts", "subtitle", "mcp_edit", "feishu_hitl", "mcp_tools"),
            skills=[
                PromptSkill(
                    name="防重图层规范",
                    content="底层模糊背景 + 主图层羽化 + 1.5% 噪点 + 水印 + 进度条；导出后重置 MD5。转场不超过 1.2s。",
                )
            ],
            mcp_servers=[
                McpServerConfig(
                    name="LocalEditExecutor",
                    transport="http",
                    url="http://127.0.0.1:8765",
                    enabled=True,
                    description="MatrixSolo 本地剪辑 MCP HTTP 执行器",
                )
            ],
        ),
        _persona(
            AgentRoleKey.OPS,
            title="运营",
            llm=LLMConfig(
                provider="grsai",
                base_url="https://grsai.dakka.com.cn/v1",
                temperature=0.65,
            ),
            tools=_tools("web_fetch", "distribute", "feishu_hitl", "bitable"),
            skills=[
                PromptSkill(
                    name="黄金时段",
                    content="早 7 点图文、午 12 点短解说、晚 18 点重磅长视频。终审未过不得排期上架。",
                )
            ],
        ),
    ]
    return {p.role: p for p in profiles}
