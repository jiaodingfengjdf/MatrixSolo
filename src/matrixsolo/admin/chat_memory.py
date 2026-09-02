from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from matrixsolo.config import get_settings

_lock = threading.Lock()
_MAX_TURNS = 12


def _path(role: str) -> Path:
    root = get_settings().data_dir / "admin" / "chat_memory"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{role}.jsonl"


def recent_turns(role: str, limit: int = 8) -> list[dict[str, str]]:
    path = _path(role)
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[dict[str, str]] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        user = str(item.get("user") or "").strip()
        assistant = str(item.get("assistant") or "").strip()
        if user and assistant:
            out.append({"user": user, "assistant": assistant})
    return out


def remember(role: str, user: str, assistant: str) -> None:
    user = user.strip()
    assistant = assistant.strip()
    if not user or not assistant:
        return
    path = _path(role)
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "user": user[:800],
        "assistant": assistant[:1200],
    }
    with _lock:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) > _MAX_TURNS * 3:
            path.write_text("\n".join(lines[-_MAX_TURNS:]) + "\n", encoding="utf-8")


def as_chat_messages(role: str, limit: int = 8) -> list[dict[str, str]]:
    msgs: list[dict[str, str]] = []
    for turn in recent_turns(role, limit=limit):
        msgs.append({"role": "user", "content": turn["user"]})
        msgs.append({"role": "assistant", "content": turn["assistant"]})
    return msgs
