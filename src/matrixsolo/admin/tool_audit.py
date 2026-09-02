from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from matrixsolo.config import get_settings

logger = logging.getLogger(__name__)


class ToolAuditStore:
    """工具调用审计 data/admin/tool_audit.jsonl."""

    def __init__(self, path: Path | None = None) -> None:
        settings = get_settings()
        self.path = path or (settings.data_dir / "admin" / "tool_audit.jsonl")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def append(
        self,
        *,
        employee_id: str,
        tool: str,
        kind: str,
        ok: bool,
        error: str = "",
        duration_ms: float = 0.0,
        params: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        row = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "employee_id": employee_id,
            "tool": tool,
            "kind": kind,
            "ok": bool(ok),
            "error": error[:2000],
            "duration_ms": round(duration_ms, 1),
            "params": params or {},
            **((extra or {}) if isinstance(extra, dict) else {}),
        }
        with self._lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    def list(
        self,
        *,
        limit: int = 200,
        employee_id: str | None = None,
        kind: str | None = None,
        tool: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if employee_id and data.get("employee_id") != employee_id:
                continue
            if kind and data.get("kind") != kind:
                continue
            if tool and data.get("tool") != tool:
                continue
            rows.append(data)
        rows.sort(key=lambda r: r.get("ts", ""), reverse=True)
        return rows[:limit]


_store: ToolAuditStore | None = None


def get_tool_audit_store() -> ToolAuditStore:
    global _store
    if _store is None:
        _store = ToolAuditStore()
    return _store
