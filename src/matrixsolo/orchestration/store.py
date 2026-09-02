from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from matrixsolo.config import get_settings
from matrixsolo.models import WorkflowState, WorkflowStatus


class WorkflowStore:
    """本地工作流持久化（可替换为 Redis / 飞书多维表格）。"""

    def __init__(self) -> None:
        self.root = get_settings().data_dir / "workflows"
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, workflow_id: str) -> Path:
        return self.root / f"{workflow_id}.json"

    def save(self, state: WorkflowState) -> None:
        self._path(state.workflow_id).write_text(
            state.model_dump_json(indent=2),
            encoding="utf-8",
        )

    def get(self, workflow_id: str) -> WorkflowState | None:
        path = self._path(workflow_id)
        if not path.exists():
            return None
        return WorkflowState.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        files = sorted(self.root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        items = []
        for path in files[:limit]:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                logs = data.get("logs") or []
                covers = data.get("covers") or []
                render = data.get("render") or {}
                items.append(
                    {
                        "workflow_id": data.get("workflow_id"),
                        "status": data.get("status"),
                        "trigger": data.get("trigger"),
                        "film": (data.get("selected_topic") or {}).get("film_name")
                        or ((data.get("topics") or [{}])[0].get("film_name") if data.get("topics") else None),
                        "created_at": data.get("created_at"),
                        "updated_at": data.get("updated_at"),
                        "error_count": len(data.get("errors") or []),
                        "cover_count": len(covers),
                        "preview_path": render.get("preview_path"),
                        "last_log": logs[-1] if logs else "",
                    }
                )
            except Exception:  # noqa: BLE001
                continue
        return items

    def update_status(self, workflow_id: str, status: WorkflowStatus) -> WorkflowState | None:
        state = self.get(workflow_id)
        if not state:
            return None
        state.status = status
        state.log(f"状态更新 → {status.value}")
        self.save(state)
        return state
