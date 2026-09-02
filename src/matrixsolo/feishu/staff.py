from __future__ import annotations

from enum import Enum
from typing import NamedTuple

from matrixsolo.config import Settings, get_settings


class AgentRole(str, Enum):
    STRATEGY = "strategy"  # 总编
    SCRIPT = "script"  # 文案
    VISUAL = "visual"  # 视觉
    EDITOR = "editor"  # 剪辑
    OPS = "ops"  # 运营


class StaffApp(NamedTuple):
    role: AgentRole
    title: str
    app_id: str
    app_secret: str


ROLE_TITLES: dict[AgentRole, str] = {
    AgentRole.STRATEGY: "总编",
    AgentRole.SCRIPT: "文案",
    AgentRole.VISUAL: "视觉",
    AgentRole.EDITOR: "剪辑",
    AgentRole.OPS: "运营",
}


def resolve_staff_apps(settings: Settings | None = None) -> dict[AgentRole, StaffApp]:
    """解析五岗飞书 AI 员工凭证；单岗未填时回退到 FEISHU_APP_ID/SECRET。"""
    s = settings or get_settings()
    fallback_id = s.feishu_app_id
    fallback_secret = s.feishu_app_secret
    mapping = {
        AgentRole.STRATEGY: (s.feishu_strategy_app_id, s.feishu_strategy_app_secret),
        AgentRole.SCRIPT: (s.feishu_script_app_id, s.feishu_script_app_secret),
        AgentRole.VISUAL: (s.feishu_visual_app_id, s.feishu_visual_app_secret),
        AgentRole.EDITOR: (s.feishu_editor_app_id, s.feishu_editor_app_secret),
        AgentRole.OPS: (s.feishu_ops_app_id, s.feishu_ops_app_secret),
    }
    apps: dict[AgentRole, StaffApp] = {}
    for role, (app_id, app_secret) in mapping.items():
        apps[role] = StaffApp(
            role=role,
            title=ROLE_TITLES[role],
            app_id=app_id or fallback_id,
            app_secret=app_secret or fallback_secret,
        )
    return apps


def staff_status(settings: Settings | None = None) -> dict[str, dict[str, str | bool]]:
    apps = resolve_staff_apps(settings)
    return {
        role.value: {
            "title": app.title,
            "app_id": app.app_id[:12] + "…" if app.app_id else "",
            "configured": bool(app.app_id and app.app_secret),
        }
        for role, app in apps.items()
    }
