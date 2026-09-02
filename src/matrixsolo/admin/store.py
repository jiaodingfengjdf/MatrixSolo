from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from matrixsolo.admin.defaults import default_profiles
from matrixsolo.admin.models import (
    AgentProfile,
    AgentProfilePatch,
    AgentRoleKey,
    McpServerConfig,
    McpServerCreate,
    McpServerUpdate,
    PromptSkill,
    PromptSkillCreate,
    PromptSkillUpdate,
    TOOL_CATALOG,
)
from matrixsolo.config import get_settings


class ProfileStore:
    """岗位 Agent 配置持久化（JSON 文件，线程安全）。"""

    def __init__(self, path: Path | None = None) -> None:
        settings = get_settings()
        self.path = path or (settings.data_dir / "admin" / "agent_profiles.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._ensure()

    def _ensure(self) -> None:
        if not self.path.exists():
            self._write(default_profiles())
            return
        # 迁移：补齐 mcp / tools；把旧版短身份升级为活人设字段
        try:
            profiles = self._read()
            changed = False
            from matrixsolo.admin.models import McpServerConfig, ToolCapability
            from matrixsolo.admin.models import TOOL_CATALOG

            catalog = {t["key"]: t for t in TOOL_CATALOG}
            defaults = default_profiles()
            legacy_identity = {
                "strategy": "你是 MatrixSolo 影视自媒体工作室的总编/策略官，负责热点挖掘与选题决策。",
                "script": "你是脚本匠，负责解说文案、Hook、标题 A/B 与头条图文。",
                "visual": "你是视觉/美术师，负责封面 A/B、Prompt 与角色一致性约束。",
                "editor": "你是剪辑/后期师，负责 TTS、字幕、MCP 自动化剪辑与成片导出。",
                "ops": "你是运营/发布员，负责多平台 SEO 元数据、排期与冷启动话术。",
            }
            persona_fields = (
                "identity",
                "personality",
                "craft",
                "work_style",
                "memory",
                "capability_boundary",
                "system_prompt",
            )
            default_on = {"web_fetch"}
            strategy_on = {"web_fetch", "browser_crawl", "hot_radar"}
            visual_on = {"web_fetch", "image_gen"}
            for role, profile in profiles.items():
                touched = False
                existing_keys = {t.key for t in profile.tools}
                for key, meta in catalog.items():
                    if key not in existing_keys:
                        enabled = (
                            key in default_on
                            or (role == "strategy" and key in strategy_on)
                            or (role == "visual" and key in visual_on)
                        )
                        profile.tools.append(
                            ToolCapability(
                                key=meta["key"],
                                name=meta["name"],
                                description=meta.get("description", ""),
                                enabled=enabled,
                            )
                        )
                        touched = True
                if role == "editor" and not profile.mcp_servers:
                    profile.mcp_servers = [
                        McpServerConfig(
                            name="LocalEditExecutor",
                            transport="http",
                            url="http://127.0.0.1:8765",
                            enabled=True,
                            description="MatrixSolo 本地剪辑 MCP HTTP 执行器",
                        )
                    ]
                    touched = True
                seeded = defaults.get(role)
                if seeded:
                    upgrade = profile.identity.strip() == legacy_identity.get(role, "")
                    for field in persona_fields:
                        current = getattr(profile, field, "") or ""
                        incoming = getattr(seeded, field, "") or ""
                        if incoming and (upgrade or not str(current).strip()):
                            setattr(profile, field, incoming)
                            touched = True
                    if role == "visual" and "禁止 JSON" in (profile.system_prompt or ""):
                        profile.system_prompt = seeded.system_prompt
                        touched = True
                if touched:
                    profile.updated_at = datetime.now(timezone.utc)
                    changed = True
                profiles[role] = profile
            if changed:
                self._write(profiles)
        except Exception:  # noqa: BLE001
            pass

    def _read(self) -> dict[str, AgentProfile]:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return {k: AgentProfile.model_validate(v) for k, v in raw.items()}

    def _write(self, profiles: dict[str, AgentProfile]) -> None:
        payload = {k: v.model_dump(mode="json") for k, v in profiles.items()}
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list(self) -> list[AgentProfile]:
        with self._lock:
            return list(self._read().values())

    def get(self, role: str | AgentRoleKey) -> AgentProfile:
        key = role.value if isinstance(role, AgentRoleKey) else role
        with self._lock:
            profiles = self._read()
            if key not in profiles:
                raise KeyError(key)
            return profiles[key]

    def get_or_create(self, role: str) -> AgentProfile:
        """按员工注册表懒创建人设；已存在则直接返回."""
        key = role.value if isinstance(role, AgentRoleKey) else role
        try:
            return self.get(key)
        except KeyError:
            profile = self._skeleton_profile(key)
            with self._lock:
                profiles = self._read()
                profiles[key] = profile
                self._write(profiles)
            return profile

    def _skeleton_profile(self, role: str) -> AgentProfile:
        from matrixsolo.admin.employees import get_employee_store
        from matrixsolo.admin.polish import default_persona_blocks

        employee = get_employee_store().get(role)
        title = (employee.title if employee else role) or role
        blocks = default_persona_blocks(title=title, function=(employee.function if employee else "") or role)
        return AgentProfile(
            role=role,
            title=title,
            enabled=True,
            **blocks,
        )

    def update(
        self,
        role: str,
        patch: AgentProfilePatch,
        *,
        version_source: str = "manual",
        version_note: str = "",
    ) -> AgentProfile:
        with self._lock:
            profiles = self._read()
            if role not in profiles:
                raise KeyError(role)
            current = profiles[role]
            data = current.model_dump()
            for field, value in patch.model_dump(exclude_unset=True).items():
                if value is not None:
                    data[field] = value
            data["updated_at"] = datetime.now(timezone.utc).isoformat()
            updated = AgentProfile.model_validate(data)
            profiles[role] = updated
            self._write(profiles)
            self._record_version_if_changed(
                role,
                current,
                updated,
                source=version_source,
                note=version_note,
            )
            return updated

    def _record_version_if_changed(
        self,
        role: str,
        before: AgentProfile,
        after: AgentProfile,
        *,
        source: str = "manual",
        note: str = "",
    ) -> None:
        from matrixsolo.admin.prompt_os import (
            get_prompt_version_store,
            persona_snapshot,
        )

        if persona_snapshot(before) == persona_snapshot(after):
            return
        get_prompt_version_store().append(
            role,
            persona_snapshot(after),
            note=note,
            source=source,
        )

    def list_prompt_versions(self, role: str) -> list[dict[str, Any]]:
        from matrixsolo.admin.prompt_os import get_prompt_version_store

        return [
            v.model_dump(mode="json")
            for v in get_prompt_version_store().list(role)
        ]

    def rollback_prompt(self, role: str, version: int) -> AgentProfile:
        from matrixsolo.admin.prompt_os import (
            apply_snapshot,
            get_prompt_version_store,
            persona_snapshot,
        )

        with self._lock:
            profiles = self._read()
            if role not in profiles:
                raise KeyError(role)
            record = get_prompt_version_store().get_version(role, version)
            if not record:
                raise KeyError(f"prompt version not found: {role}@{version}")
            current = profiles[role]
            apply_snapshot(current, record.snapshot)
            current.updated_at = datetime.now(timezone.utc)
            profiles[role] = current
            self._write(profiles)
            get_prompt_version_store().append(
                role,
                persona_snapshot(current),
                note=f"回滚到 v{version}",
                source="rollback",
            )
            return current

    def add_skill(self, role: str, body: PromptSkillCreate) -> AgentProfile:
        with self._lock:
            profiles = self._read()
            profile = profiles[role]
            skill = PromptSkill(
                name=body.name,
                content=body.content,
                enabled=body.enabled,
                source=body.source,
                origin=body.origin,
                description=body.description,
            )
            profile.skills.append(skill)
            profile.updated_at = datetime.now(timezone.utc)
            profiles[role] = profile
            self._write(profiles)
            return profile

    def install_skill(self, role: str, skill: PromptSkill) -> AgentProfile:
        with self._lock:
            profiles = self._read()
            if role not in profiles:
                raise KeyError(role)
            profile = profiles[role]
            for existing in profile.skills:
                same_origin = skill.origin and existing.origin == skill.origin
                same_name = existing.name == skill.name
                if same_origin or (same_name and skill.source != "manual"):
                    existing.content = skill.content
                    existing.description = skill.description or existing.description
                    existing.origin = skill.origin or existing.origin
                    existing.source = skill.source
                    existing.enabled = True
                    profile.updated_at = datetime.now(timezone.utc)
                    profiles[role] = profile
                    self._write(profiles)
                    return profile
            profile.skills.append(skill)
            profile.updated_at = datetime.now(timezone.utc)
            profiles[role] = profile
            self._write(profiles)
            return profile

    def update_skill(self, role: str, skill_id: str, body: PromptSkillUpdate) -> AgentProfile:
        with self._lock:
            profiles = self._read()
            profile = profiles[role]
            for i, skill in enumerate(profile.skills):
                if skill.id == skill_id:
                    data = skill.model_dump()
                    for field, value in body.model_dump(exclude_unset=True).items():
                        if value is not None:
                            data[field] = value
                    profile.skills[i] = PromptSkill.model_validate(data)
                    profile.updated_at = datetime.now(timezone.utc)
                    profiles[role] = profile
                    self._write(profiles)
                    return profile
            raise KeyError(skill_id)

    def delete_skill(self, role: str, skill_id: str) -> AgentProfile:
        with self._lock:
            profiles = self._read()
            profile = profiles[role]
            before = len(profile.skills)
            profile.skills = [s for s in profile.skills if s.id != skill_id]
            if len(profile.skills) == before:
                raise KeyError(skill_id)
            profile.updated_at = datetime.now(timezone.utc)
            profiles[role] = profile
            self._write(profiles)
            return profile

    def add_mcp(self, role: str, body: McpServerCreate) -> AgentProfile:
        with self._lock:
            profiles = self._read()
            profile = profiles[role]
            server = McpServerConfig(**body.model_dump())
            profile.mcp_servers.append(server)
            profile.updated_at = datetime.now(timezone.utc)
            profiles[role] = profile
            self._write(profiles)
            return profile

    def update_mcp(self, role: str, mcp_id: str, body: McpServerUpdate) -> AgentProfile:
        with self._lock:
            profiles = self._read()
            profile = profiles[role]
            for i, server in enumerate(profile.mcp_servers):
                if server.id == mcp_id:
                    data = server.model_dump()
                    for field, value in body.model_dump(exclude_unset=True).items():
                        if value is not None:
                            data[field] = value
                    profile.mcp_servers[i] = McpServerConfig.model_validate(data)
                    profile.updated_at = datetime.now(timezone.utc)
                    profiles[role] = profile
                    self._write(profiles)
                    return profile
            raise KeyError(mcp_id)

    def delete_mcp(self, role: str, mcp_id: str) -> AgentProfile:
        with self._lock:
            profiles = self._read()
            profile = profiles[role]
            before = len(profile.mcp_servers)
            profile.mcp_servers = [s for s in profile.mcp_servers if s.id != mcp_id]
            if len(profile.mcp_servers) == before:
                raise KeyError(mcp_id)
            profile.updated_at = datetime.now(timezone.utc)
            profiles[role] = profile
            self._write(profiles)
            return profile

    def reset_defaults(self) -> list[AgentProfile]:
        with self._lock:
            profiles = default_profiles()
            self._write(profiles)
            return list(profiles.values())

    def tool_catalog(self) -> list[dict[str, str]]:
        return list(TOOL_CATALOG)


_store: ProfileStore | None = None


def get_profile_store() -> ProfileStore:
    global _store
    if _store is None:
        _store = ProfileStore()
    return _store
