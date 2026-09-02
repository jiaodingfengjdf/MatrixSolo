from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from matrixsolo.config import get_settings

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class StudioPrompt(BaseModel):
    """L0 工作室层：可编辑全局守则（默认 STUDIO_VOICE + COLLEAGUES）."""

    studio_voice: str = ""
    colleagues: str = ""
    updated_at: datetime = Field(default_factory=_utcnow)

    def is_default(self) -> bool:
        return not self.studio_voice.strip() and not self.colleagues.strip()


class PromptVersion(BaseModel):
    employee_id: str
    version: int
    snapshot: dict[str, str] = Field(default_factory=dict)
    note: str = ""
    source: str = "manual"  # manual / polish / rollback / start
    created_at: datetime = Field(default_factory=_utcnow)


class StudioPromptStore:
    """L0 工作室守则持久化 data/admin/studio_prompt.json."""

    def __init__(self, path: Path | None = None) -> None:
        settings = get_settings()
        self.path = path or (settings.data_dir / "admin" / "studio_prompt.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._ensure()

    def _ensure(self) -> None:
        if not self.path.exists():
            self._write(StudioPrompt())

    def _read(self) -> StudioPrompt:
        if not self.path.exists():
            return StudioPrompt()
        return StudioPrompt.model_validate_json(self.path.read_text(encoding="utf-8"))

    def _write(self, prompt: StudioPrompt) -> None:
        self.path.write_text(
            prompt.model_dump_json(indent=2),
            encoding="utf-8",
        )

    def get(self) -> StudioPrompt:
        with self._lock:
            return self._read()

    def update(self, studio_voice: str, colleagues: str) -> StudioPrompt:
        with self._lock:
            prompt = StudioPrompt(
                studio_voice=studio_voice,
                colleagues=colleagues,
                updated_at=_utcnow(),
            )
            self._write(prompt)
            return prompt


class PromptVersionStore:
    """Prompt 版本回滚：data/admin/prompt_versions/{employee_id}.jsonl."""

    def __init__(self, path: Path | None = None) -> None:
        settings = get_settings()
        self.root = path or (settings.data_dir / "admin" / "prompt_versions")
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, employee_id: str) -> Path:
        safe = employee_id.replace("/", "_").replace("\\", "_").strip()
        return self.root / f"{safe}.jsonl"

    def list(self, employee_id: str) -> list[PromptVersion]:
        path = self._path(employee_id)
        if not path.exists():
            return []
        versions: list[PromptVersion] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                versions.append(PromptVersion.model_validate_json(line))
            except Exception:  # noqa: BLE001
                logger.debug("skip invalid prompt version line")
                continue
        return sorted(versions, key=lambda v: v.version)

    def latest_version(self, employee_id: str) -> int:
        versions = self.list(employee_id)
        return versions[-1].version if versions else 0

    def append(
        self,
        employee_id: str,
        snapshot: dict[str, str],
        *,
        note: str = "",
        source: str = "manual",
    ) -> PromptVersion:
        with self._lock:
            version = self.latest_version(employee_id) + 1
            record = PromptVersion(
                employee_id=employee_id,
                version=version,
                snapshot=dict(snapshot),
                note=note,
                source=source,
            )
            with self._path(employee_id).open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
            return record

    def get_version(self, employee_id: str, version: int) -> PromptVersion | None:
        return next(
            (v for v in self.list(employee_id) if v.version == version),
            None,
        )


def estimate_tokens(text: str) -> int:
    """按 PRD: 字符数 / 4 近似估算 token."""
    return max(0, len(text or "") // 4)


def persona_snapshot(profile: Any) -> dict[str, str]:
    return {
        "title": profile.title or "",
        "identity": profile.identity or "",
        "personality": profile.personality or "",
        "craft": profile.craft or "",
        "work_style": profile.work_style or "",
        "memory": profile.memory or "",
        "capability_boundary": profile.capability_boundary or "",
        "system_prompt": profile.system_prompt or "",
    }


def apply_snapshot(profile: Any, snapshot: dict[str, str]) -> None:
    for field in (
        "identity",
        "personality",
        "craft",
        "work_style",
        "memory",
        "capability_boundary",
        "system_prompt",
    ):
        if field in snapshot:
            setattr(profile, field, snapshot[field])
    if snapshot.get("title"):
        profile.title = snapshot["title"]


def compose_layered(profile: Any, *, department: str | None = None) -> str:
    """四层 Prompt OS：L0 工作室 → L1 部门 → L2 岗位 → L3 任务 → 工具 → Skills → MCP."""
    store = StudioPromptStore()
    prompt = store.get()
    from matrixsolo.admin.personas import COLLEAGUES, STUDIO_VOICE

    studio_voice = prompt.studio_voice.strip() or STUDIO_VOICE.strip()
    colleagues = prompt.colleagues.strip() or COLLEAGUES.strip()
    parts: list[str] = []
    parts.append(f"## 活人感守则 (L0 工作室)\n{studio_voice}")
    parts.append(f"## 工作室共识 (L0 工作室)\n{colleagues}")

    if department:
        # L1 部门 SOP（部门实体落地后从 departments.json 读取）
        parts.append(f"## 部门 SOP (L1 {department})")

    # L2 岗位六段
    if profile.identity.strip():
        parts.append(f"## 身份设定 (L2)\n{profile.identity.strip()}")
    if profile.personality.strip():
        parts.append(f"## 专属性格 (L2)\n{profile.personality.strip()}")
    if profile.craft.strip():
        parts.append(f"## 专属职业能力 (L2)\n{profile.craft.strip()}")
    if profile.work_style.strip():
        parts.append(f"## 专属做事风格 (L2)\n{profile.work_style.strip()}")
    if profile.memory.strip():
        parts.append(f"## 专属记忆 (L2)\n{profile.memory.strip()}")
    if profile.capability_boundary.strip():
        parts.append(f"## 能力边界 (L2)\n{profile.capability_boundary.strip()}")

    # L3 任务契约
    if profile.system_prompt.strip():
        parts.append(f"## 任务契约 (L3)\n{profile.system_prompt.strip()}")

    enabled_tools = [t for t in profile.tools if t.enabled]
    if enabled_tools:
        tool_lines = "\n".join(f"- {t.key}：{t.description or t.name}" for t in enabled_tools)
        parts.append(
            "## 已启用内置技能\n"
            f"{tool_lines}\n"
            "热榜/选题必须自己用 hot_radar 或 web_fetch，禁止问老板要片名，也不要把爬虫甩给运营。"
        )

    enabled_skills = [s for s in profile.skills if s.enabled and s.content.strip()]
    if enabled_skills:
        skill_block = "\n\n".join(
            f"### Skill: {s.name}\n{s.content.strip()}" for s in enabled_skills
        )
        parts.append(f"## 已启用 Skills\n{skill_block}")

    enabled_mcp = [m for m in profile.mcp_servers if m.enabled]
    if enabled_mcp:
        mcp_lines = "\n".join(f"- {m.name} ({m.transport}) {m.url or m.command}" for m in enabled_mcp)
        parts.append(f"## 已接入 MCP\n{mcp_lines}")

    return "\n\n".join(p for p in parts if p)


_studio: StudioPromptStore | None = None
_versions: PromptVersionStore | None = None


def get_studio_prompt_store() -> StudioPromptStore:
    global _studio
    if _studio is None:
        _studio = StudioPromptStore()
    return _studio


def get_prompt_version_store() -> PromptVersionStore:
    global _versions
    if _versions is None:
        _versions = PromptVersionStore()
    return _versions
