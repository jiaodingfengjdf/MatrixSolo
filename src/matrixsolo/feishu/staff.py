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
    role: str
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


def resolve_staff_apps(settings: Settings | None = None) -> dict[str, StaffApp]:
    """解析飞书 AI 员工凭证：五岗 env + 员工注册表；单岗未填时回退 FEISHU_APP_ID/SECRET。"""
    s = settings or get_settings()
    fallback_id = s.feishu_app_id
    fallback_secret = s.feishu_app_secret
    mapping = {
        AgentRole.STRATEGY.value: (AgentRole.STRATEGY, s.feishu_strategy_app_id, s.feishu_strategy_app_secret),
        AgentRole.SCRIPT.value: (AgentRole.SCRIPT, s.feishu_script_app_id, s.feishu_script_app_secret),
        AgentRole.VISUAL.value: (AgentRole.VISUAL, s.feishu_visual_app_id, s.feishu_visual_app_secret),
        AgentRole.EDITOR.value: (AgentRole.EDITOR, s.feishu_editor_app_id, s.feishu_editor_app_secret),
        AgentRole.OPS.value: (AgentRole.OPS, s.feishu_ops_app_id, s.feishu_ops_app_secret),
    }
    apps: dict[str, StaffApp] = {}
    for key, (role, app_id, app_secret) in mapping.items():
        apps[key] = StaffApp(
            role=key,
            title=ROLE_TITLES[role],
            app_id=app_id or fallback_id,
            app_secret=app_secret or fallback_secret,
        )
    try:
        from matrixsolo.admin.employees import get_employee_store

        for employee in get_employee_store().active():
            if employee.id in apps:
                continue
            apps[employee.id] = StaffApp(
                role=employee.id,
                title=employee.title or employee.display_name or employee.id,
                app_id=employee.app_id,
                app_secret=employee.app_secret,
            )
    except Exception:  # noqa: BLE001
        pass
    return apps


def employee_title(employee_id: str) -> str:
    if employee_id in ROLE_TITLES:
        return ROLE_TITLES[employee_id]
    try:
        from matrixsolo.admin.employees import get_employee_store

        employee = get_employee_store().get(employee_id)
        if employee:
            return employee.title or employee.display_name or employee_id
    except Exception:  # noqa: BLE001
        pass
    return employee_id


def employee_title_map() -> dict[str, str]:
    """花名/显示名 → employee_id（含注册表新员工），供飞书 mention 解析."""
    out: dict[str, str] = {}
    for role, title in ROLE_TITLES.items():
        out[title] = role.value
    try:
        from matrixsolo.admin.employees import get_employee_store

        for employee in get_employee_store().list():
            for name in (employee.title, employee.display_name):
                if name and name not in out:
                    out[name] = employee.id
    except Exception:  # noqa: BLE001
        pass
    return out


def staff_status(settings: Settings | None = None) -> dict[str, dict[str, str | bool]]:
    apps = resolve_staff_apps(settings)
    return {
        role: {
            "title": app.title,
            "app_id": app.app_id[:12] + "…" if app.app_id else "",
            "configured": bool(app.app_id and app.app_secret),
        }
        for role, app in apps.items()
    }
