from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from matrixsolo.config import get_settings

_lock = threading.Lock()


def _studio_path() -> Path:
    root = get_settings().data_dir / "admin"
    root.mkdir(parents=True, exist_ok=True)
    return root / "studio_huddle.json"


def _calendar_path() -> Path:
    root = get_settings().data_dir / "admin"
    root.mkdir(parents=True, exist_ok=True)
    return root / "content_calendar.jsonl"


def save_studio_context(
    *,
    chat_id: str = "",
    workflow_id: str = "",
    job: str = "",
    film_name: str = "",
    angle: str = "",
    mood: str = "",
    brief: str = "",
    hook: str = "",
    user_text: str = "",
    image_paths: list[str] | None = None,
) -> dict[str, Any]:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "chat_id": chat_id,
        "workflow_id": workflow_id,
        "job": job,
        "film_name": film_name,
        "angle": angle,
        "mood": mood,
        "brief": brief,
        "hook": hook,
        "user_text": (user_text or "")[:400],
        "image_paths": [p for p in (image_paths or []) if p][:6],
    }
    with _lock:
        _studio_path().write_text(
            json.dumps(record, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return record


def load_studio_context() -> dict[str, Any] | None:
    path = _studio_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def format_studio_context(limit: int = 600) -> str:
    data = load_studio_context()
    if not data:
        return ""
    film = str(data.get("film_name") or "").strip()
    job = str(data.get("job") or "").strip()
    if not (film or job or data.get("user_text")):
        return ""
    lines = [
        "【工作室最近一期 huddle，五岗共用，接着干不要另起炉灶】",
        f"任务：{job or 'talk'}  主题：{film or '-'}",
        f"切口：{data.get('angle') or '-'}  情绪：{data.get('mood') or '-'}",
    ]
    if data.get("brief"):
        lines.append(f"方向：{data['brief']}")
    if data.get("hook"):
        lines.append(f"钩子：{data['hook']}")
    if data.get("user_text"):
        lines.append(f"老板原话：{data['user_text']}")
    if data.get("image_paths"):
        lines.append(f"已出图 {len(data['image_paths'])} 张")
    text = "\n".join(lines)
    return text[:limit]


def append_calendar_rows(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path = _calendar_path()
    with _lock:
        with path.open("a", encoding="utf-8") as handle:
            for row in rows:
                payload = {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    **{k: v for k, v in row.items() if v is not None},
                }
                handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def recent_calendar(limit: int = 20) -> list[dict[str, Any]]:
    path = _calendar_path()
    if not path.is_file():
        return []
    items: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            items.append(row)
    items.reverse()
    return items


def recent_feishu_traces(limit: int = 80) -> list[dict[str, Any]]:
    path = get_settings().data_dir / "logs" / "feishu_in.jsonl"
    if not path.is_file():
        return []
    items: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            items.append(row)
    items.reverse()
    return items
