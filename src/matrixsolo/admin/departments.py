from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from matrixsolo.config import get_settings


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Department(BaseModel):
    """部门 = 工作群：一个群只能绑一个部门，隔离记忆/日历/HITL/模板."""

    id: str
    name: str
    platform: Literal["toutiao", "douyin", "bilibili", "other"] = "other"
    chat_id: str = ""
    hitl_chat_id: str = ""  # 默认取 chat_id
    member_employee_ids: list[str] = Field(
        default_factory=lambda: ["strategy", "script", "visual", "editor", "ops"]
    )
    pipeline_template: list[str] = Field(
        default_factory=lambda: ["strategy", "script", "visual", "editor", "ops"]
    )
    enabled: bool = True
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    def target_chat_id(self) -> str:
        return self.hitl_chat_id or self.chat_id or ""


class DepartmentCreate(BaseModel):
    id: str
    name: str
    platform: Literal["toutiao", "douyin", "bilibili", "other"] = "other"
    chat_id: str = ""
    hitl_chat_id: str = ""
    member_employee_ids: list[str] = Field(
        default_factory=lambda: ["strategy", "script", "visual", "editor", "ops"]
    )
    pipeline_template: list[str] = Field(
        default_factory=lambda: ["strategy", "script", "visual", "editor", "ops"]
    )


class DepartmentUpdate(BaseModel):
    name: str | None = None
    platform: Literal["toutiao", "douyin", "bilibili", "other"] | None = None
    chat_id: str | None = None
    hitl_chat_id: str | None = None
    member_employee_ids: list[str] | None = None
    pipeline_template: list[str] | None = None
    enabled: bool | None = None


class DepartmentChatBind(BaseModel):
    chat_id: str


def _default_presets() -> list[Department]:
    return [
        Department(
            id="toutiao",
            name="头条图文部",
            platform="toutiao",
            member_employee_ids=["strategy", "script", "visual", "ops"],
            pipeline_template=["strategy", "script", "visual", "ops"],
        ),
        Department(
            id="douyin",
            name="视频抖音部",
            platform="douyin",
            member_employee_ids=["strategy", "script", "visual", "editor", "ops"],
            pipeline_template=["strategy", "script", "visual", "editor", "ops"],
        ),
        Department(
            id="bilibili",
            name="视频哔哩哔哩部",
            platform="bilibili",
            member_employee_ids=["strategy", "script", "visual", "editor", "ops"],
            pipeline_template=["strategy", "script", "visual", "editor", "ops"],
        ),
    ]


class DepartmentStore:
    """部门持久化 data/admin/departments.json."""

    def __init__(self, path=None) -> None:
        settings = get_settings()
        self.path = path or (settings.data_dir / "admin" / "departments.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._ensure()

    def _ensure(self) -> None:
        if not self.path.exists():
            self._write(_default_presets())

    def _read(self) -> list[Department]:
        if not self.path.exists():
            return _default_presets()
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return [Department.model_validate(r) for r in raw.get("departments", [])]

    def _write(self, rows: list[Department]) -> None:
        payload = {"departments": [d.model_dump(mode="json") for d in rows]}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def list(self) -> list[Department]:
        with self._lock:
            return self._read()

    def get(self, department_id: str) -> Department | None:
        with self._lock:
            return next((d for d in self._read() if d.id == department_id), None)

    def create(self, body: DepartmentCreate) -> Department:
        with self._lock:
            rows = self._read()
            if any(d.id == body.id for d in rows):
                raise ValueError(f"部门 id 已存在: {body.id}")
            self._assert_chat_unique(body.chat_id, rows, exclude=body.id)
            department = Department(id=body.id, **body.model_dump(exclude={"id"}))
            rows.append(department)
            self._write(rows)
            return department

    def update(self, department_id: str, body: DepartmentUpdate) -> Department:
        with self._lock:
            rows = self._read()
            index = next((i for i, d in enumerate(rows) if d.id == department_id), None)
            if index is None:
                raise KeyError(department_id)
            data = rows[index].model_dump()
            for field, value in body.model_dump(exclude_unset=True).items():
                if value is not None:
                    data[field] = value
            if data.get("hitl_chat_id") in (None, ""):
                data["hitl_chat_id"] = data.get("chat_id") or ""
            data["updated_at"] = _utcnow().isoformat()
            updated = Department.model_validate(data)
            self._assert_chat_unique(updated.chat_id, rows, exclude=department_id)
            rows[index] = updated
            self._write(rows)
            return updated

    def delete(self, department_id: str) -> None:
        with self._lock:
            rows = self._read()
            if not any(d.id == department_id for d in rows):
                raise KeyError(department_id)
            rows = [d for d in rows if d.id != department_id]
            self._write(rows)

    def bind_chat(self, department_id: str, chat_id: str) -> Department:
        chat_id = (chat_id or "").strip()
        if not chat_id:
            raise ValueError("chat_id 不能为空")
        with self._lock:
            rows = self._read()
            index = next((i for i, d in enumerate(rows) if d.id == department_id), None)
            if index is None:
                raise KeyError(department_id)
            self._assert_chat_unique(chat_id, rows, exclude=department_id)
            rows[index].chat_id = chat_id
            if not rows[index].hitl_chat_id:
                rows[index].hitl_chat_id = chat_id
            rows[index].updated_at = _utcnow()
            self._write(rows)
            return rows[index]

    def resolve_by_chat(self, chat_id: str) -> Department | None:
        chat_id = (chat_id or "").strip()
        if not chat_id:
            return None
        with self._lock:
            return next(
                (d for d in self._read() if d.enabled and d.chat_id == chat_id),
                None,
            )

    def _assert_chat_unique(
        self,
        chat_id: str,
        rows: list[Department],
        *,
        exclude: str,
    ) -> None:
        if not chat_id:
            return
        if any(
            d.chat_id == chat_id and d.id != exclude
            for d in rows
        ):
            raise ValueError(f"chat_id 已被其他部门绑定: {chat_id}")


_store: DepartmentStore | None = None


def get_department_store() -> DepartmentStore:
    global _store
    if _store is None:
        _store = DepartmentStore()
    return _store
