from __future__ import annotations

import hashlib
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from matrixsolo.config import get_settings

logger = logging.getLogger(__name__)

_BUSINESS_TZ = ZoneInfo("Asia/Shanghai")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def business_today() -> str:
    return datetime.now(_BUSINESS_TZ).date().isoformat()


def make_log_id(date: str, workflow_id: str, work_type: str, stage: str, employee_id: str) -> str:
    raw = f"{date}|{workflow_id}|{work_type}|{stage}|{employee_id}".strip("|")
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


class WorkLog(BaseModel):
    log_id: str
    date: str = Field(default_factory=business_today)
    department_id: str = "default"
    department_name: str = "默认"
    employee_id: str = ""
    employee_title: str = ""
    project: str = ""
    work_type: Literal["huddle", "hitl", "workflow", "manual"] = "manual"
    status: Literal["started", "blocked", "done", "failed"] = "done"
    summary: str = ""
    artifact_url: str = ""
    workflow_id: str = ""
    chat_id: str = ""
    stage: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class WorkLogCreate(BaseModel):
    date: str | None = None
    department_id: str = "default"
    department_name: str = "默认"
    employee_id: str = ""
    employee_title: str = ""
    project: str = ""
    work_type: Literal["huddle", "hitl", "workflow", "manual"] = "manual"
    status: Literal["started", "blocked", "done", "failed"] = "done"
    summary: str = ""
    artifact_url: str = ""
    workflow_id: str = ""
    chat_id: str = ""
    stage: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)


class WorkLogStore:
    """每日工作记录本地镜像 data/admin/work_logs.jsonl（断网兜底，飞书表为主展示）."""

    def __init__(self, path: Path | None = None) -> None:
        settings = get_settings()
        self.path = path or (settings.data_dir / "admin" / "work_logs.jsonl")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _read_all(self) -> list[WorkLog]:
        if not self.path.exists():
            return []
        rows: list[WorkLog] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(WorkLog.model_validate_json(line))
            except Exception:  # noqa: BLE001
                logger.debug("skip invalid work log line")
                continue
        return rows

    def _write_all(self, rows: list[WorkLog]) -> None:
        with self.path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(row.model_dump_json() + "\n")

    def upsert(self, log: WorkLog) -> WorkLog:
        with self._lock:
            rows = self._read_all()
            for i, existing in enumerate(rows):
                if existing.log_id == log.log_id:
                    log.created_at = existing.created_at
                    rows[i] = log
                    self._write_all(rows)
                    return log
            rows.append(log)
            self._write_all(rows)
            return log

    def list(
        self,
        *,
        limit: int = 200,
        date_from: str | None = None,
        date_to: str | None = None,
        department_id: str | None = None,
        employee_id: str | None = None,
        status: str | None = None,
        work_type: str | None = None,
    ) -> list[WorkLog]:
        with self._lock:
            rows = self._read_all()
        if date_from:
            rows = [r for r in rows if r.date >= date_from]
        if date_to:
            rows = [r for r in rows if r.date <= date_to]
        if department_id:
            rows = [r for r in rows if r.department_id == department_id]
        if employee_id:
            rows = [r for r in rows if r.employee_id == employee_id]
        if status:
            rows = [r for r in rows if r.status == status]
        if work_type:
            rows = [r for r in rows if r.work_type == work_type]
        rows.sort(key=lambda r: r.created_at, reverse=True)
        return rows[:limit]

    def count_by_date(self, date: str) -> int:
        with self._lock:
            return sum(1 for r in self._read_all() if r.date == date)


_store: WorkLogStore | None = None


def get_work_log_store() -> WorkLogStore:
    global _store
    if _store is None:
        _store = WorkLogStore()
    return _store


async def record_work_log(
    *,
    project: str = "",
    work_type: Literal["huddle", "hitl", "workflow", "manual"] = "manual",
    status: Literal["started", "blocked", "done", "failed"] = "done",
    summary: str = "",
    workflow_id: str = "",
    chat_id: str = "",
    stage: str = "",
    employee_id: str = "",
    employee_title: str = "",
    department_id: str = "default",
    department_name: str = "默认",
    artifact_url: str = "",
    extra: dict[str, Any] | None = None,
) -> WorkLog | None:
    """幂等写工作记录（本地必有）；若已配飞书表则同步写表。任何异常都不阻断主流程。"""
    try:
        date = business_today()
        log_id = make_log_id(date, workflow_id, work_type, stage, employee_id)
        log = WorkLog(
            log_id=log_id,
            date=date,
            project=project,
            work_type=work_type,
            status=status,
            summary=summary,
            workflow_id=workflow_id,
            chat_id=chat_id,
            stage=stage,
            employee_id=employee_id,
            employee_title=employee_title,
            department_id=department_id,
            department_name=department_name,
            artifact_url=artifact_url,
            extra=extra or {},
        )
        get_work_log_store().upsert(log)
        await _write_feishu_if_configured(log)
        return log
    except Exception:
        logger.exception("record_work_log failed")
        return None


async def _write_feishu_if_configured(log: WorkLog) -> None:
    from matrixsolo.feishu.client import FeishuClient

    await FeishuClient().write_work_log(log)
