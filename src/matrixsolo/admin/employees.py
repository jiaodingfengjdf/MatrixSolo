from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from matrixsolo.config import Settings, get_settings


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _mask_secret(secret: str) -> str:
    if not secret:
        return ""
    if len(secret) <= 8:
        return "****"
    return f"{secret[:4]}****{secret[-4:]}"


class Employee(BaseModel):
    """数字员工注册表：id 稳定字符串，不再要求属于五值枚举."""

    id: str
    title: str = ""  # 花名 / 群内显示名
    display_name: str = ""  # 飞书开放平台应用名（可选）
    function: str = ""  # strategy/script/visual/editor/ops 或自定义职能标签
    app_id: str = ""
    app_secret: str = ""  # 仅服务端存储
    department_ids: list[str] = Field(default_factory=list)
    avatar_name: str = ""
    voice_id: str = ""
    portrait_asset_id: str = ""
    digital_human_id: str = ""
    digital_human_enabled: bool = False
    enabled: bool = True
    builtin: bool = False
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    def dump_admin(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["app_secret_masked"] = _mask_secret(self.app_secret)
        data["has_credentials"] = bool(self.app_id and self.app_secret)
        data.pop("app_secret", None)
        return data


class EmployeeCreate(BaseModel):
    id: str
    title: str
    display_name: str = ""
    function: str = ""
    app_id: str = ""
    app_secret: str = ""
    department_ids: list[str] = Field(default_factory=list)
    avatar_name: str = ""
    voice_id: str = ""
    portrait_asset_id: str = ""
    digital_human_id: str = ""
    digital_human_enabled: bool = False


class EmployeeUpdate(BaseModel):
    title: str | None = None
    display_name: str | None = None
    function: str | None = None
    app_id: str | None = None
    app_secret: str | None = None
    department_ids: list[str] | None = None
    avatar_name: str | None = None
    voice_id: str | None = None
    portrait_asset_id: str | None = None
    digital_human_id: str | None = None
    digital_human_enabled: bool | None = None


class EmployeePolishRequest(BaseModel):
    """一键润色输入."""

    one_liner: str = ""
    department: str = ""
    on_camera: bool = False
    clone_from: str = ""


def builtin_employee_seeds(settings: Settings | None = None) -> list[Employee]:
    s = settings or get_settings()
    rows = [
        ("strategy", "总编", (s.feishu_strategy_app_id, s.feishu_strategy_app_secret)),
        ("script", "文案", (s.feishu_script_app_id, s.feishu_script_app_secret)),
        ("visual", "视觉", (s.feishu_visual_app_id, s.feishu_visual_app_secret)),
        ("editor", "剪辑", (s.feishu_editor_app_id, s.feishu_editor_app_secret)),
        ("ops", "运营", (s.feishu_ops_app_id, s.feishu_ops_app_secret)),
    ]
    fallback_id, fallback_secret = s.feishu_app_id, s.feishu_app_secret
    return [
        Employee(
            id=role,
            title=title,
            display_name=title,
            function=role,
            app_id=app_id or fallback_id,
            app_secret=app_secret or fallback_secret,
            builtin=True,
            enabled=True,
        )
        for role, title, (app_id, app_secret) in rows
    ]


class EmployeeStore:
    """员工注册表持久化 data/admin/employees.json + 动态首启种子."""

    def __init__(self, path=None) -> None:
        settings = get_settings()
        self.path = path or (settings.data_dir / "admin" / "employees.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._ensure()

    def _ensure(self) -> None:
        if not self.path.exists():
            self._write(builtin_employee_seeds())

    def _read(self) -> list[Employee]:
        if not self.path.exists():
            return builtin_employee_seeds()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            rows = [Employee.model_validate(r) for r in raw.get("employees", raw if isinstance(raw, list) else [])]
        except Exception:  # noqa: BLE001
            return builtin_employee_seeds()
        # 保证内置五岗永远存在（即使文件被手删/迁移）
        existing = {e.id for e in rows}
        for seed in builtin_employee_seeds():
            if seed.id not in existing:
                rows.append(seed)
        return rows

    def _write(self, rows: list[Employee]) -> None:
        payload = {"employees": [e.model_dump(mode="json") for e in rows]}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def list(self) -> list[Employee]:
        with self._lock:
            return self._read()

    def active(self) -> list[Employee]:
        return [e for e in self.list() if e.enabled and e.app_id and e.app_secret]

    def get(self, employee_id: str) -> Employee | None:
        with self._lock:
            return next((e for e in self._read() if e.id == employee_id), None)

    def create(self, body: EmployeeCreate) -> Employee:
        with self._lock:
            rows = self._read()
            if any(e.id == body.id for e in rows):
                raise ValueError(f"员工 id 已存在: {body.id}")
            employee = Employee(id=body.id, **body.model_dump(exclude={"id"}))
            employee.builtin = False
            rows.append(employee)
            self._write(rows)
            return employee

    def update(self, employee_id: str, body: EmployeeUpdate) -> Employee:
        with self._lock:
            rows = self._read()
            index = next((i for i, e in enumerate(rows) if e.id == employee_id), None)
            if index is None:
                raise KeyError(employee_id)
            data = rows[index].model_dump()
            for field, value in body.model_dump(exclude_unset=True).items():
                if field == "app_secret":
                    if value:
                        data[field] = value
                elif value is not None:
                    data[field] = value
            data["updated_at"] = _utcnow().isoformat()
            updated = Employee.model_validate(data)
            rows[index] = updated
            self._write(rows)
            return updated

    def set_enabled(self, employee_id: str, enabled: bool) -> Employee:
        with self._lock:
            rows = self._read()
            index = next((i for i, e in enumerate(rows) if e.id == employee_id), None)
            if index is None:
                raise KeyError(employee_id)
            rows[index].enabled = enabled
            rows[index].updated_at = _utcnow()
            self._write(rows)
            return rows[index]


_store: EmployeeStore | None = None


def get_employee_store() -> EmployeeStore:
    global _store
    if _store is None:
        _store = EmployeeStore()
    return _store
