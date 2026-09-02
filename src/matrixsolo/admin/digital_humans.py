from __future__ import annotations

import json
import threading
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from matrixsolo.config import get_settings


def _utcnow() -> datetime:
    return datetime.now(UTC)


class DigitalHumanAsset(BaseModel):
    """数字人形象层资产：声线/形象参考/口播模板；不代建真人素材."""

    id: str
    name: str
    provider: str = "edge-tts"  # edge-tts / azure / 三方口播供应商（待决策）
    voice_id: str = ""
    portrait_asset_id: str = ""
    portrait_path: str = ""
    avatar_name: str = ""
    opening_script: str = ""
    subtitle_style: str = ""
    enabled: bool = True
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class DigitalHumanCreate(BaseModel):
    id: str
    name: str
    provider: str = "edge-tts"
    voice_id: str = ""
    portrait_asset_id: str = ""
    portrait_path: str = ""
    avatar_name: str = ""
    opening_script: str = ""
    subtitle_style: str = ""
    enabled: bool = True


class DigitalHumanUpdate(BaseModel):
    name: str | None = None
    provider: str | None = None
    voice_id: str | None = None
    portrait_asset_id: str | None = None
    portrait_path: str | None = None
    avatar_name: str | None = None
    opening_script: str | None = None
    subtitle_style: str | None = None
    enabled: bool | None = None


class DigitalHumanStore:
    """数字人资产登记 data/admin/digital_humans.json."""

    def __init__(self, path=None) -> None:
        settings = get_settings()
        self.path = path or (settings.data_dir / "admin" / "digital_humans.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._ensure()

    def _ensure(self) -> None:
        if not self.path.exists():
            self._write(_default_assets())

    def _read(self) -> list[DigitalHumanAsset]:
        if not self.path.exists():
            return _default_assets()
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return [DigitalHumanAsset.model_validate(r) for r in raw.get("assets", [])]

    def _write(self, rows: list[DigitalHumanAsset]) -> None:
        payload = {"assets": [a.model_dump(mode="json") for a in rows]}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def list(self) -> list[DigitalHumanAsset]:
        with self._lock:
            return self._read()

    def get(self, asset_id: str) -> DigitalHumanAsset | None:
        with self._lock:
            return next((a for a in self._read() if a.id == asset_id), None)

    def create(self, body: DigitalHumanCreate) -> DigitalHumanAsset:
        with self._lock:
            rows = self._read()
            if any(a.id == body.id for a in rows):
                raise ValueError(f"数字人资产 id 已存在: {body.id}")
            asset = DigitalHumanAsset(id=body.id, **body.model_dump(exclude={"id"}))
            rows.append(asset)
            self._write(rows)
            return asset

    def update(self, asset_id: str, body: DigitalHumanUpdate) -> DigitalHumanAsset:
        with self._lock:
            rows = self._read()
            index = next((i for i, a in enumerate(rows) if a.id == asset_id), None)
            if index is None:
                raise KeyError(asset_id)
            data = rows[index].model_dump()
            for field, value in body.model_dump(exclude_unset=True).items():
                if value is not None:
                    data[field] = value
            data["updated_at"] = _utcnow().isoformat()
            updated = DigitalHumanAsset.model_validate(data)
            rows[index] = updated
            self._write(rows)
            return updated

    def delete(self, asset_id: str) -> None:
        with self._lock:
            rows = self._read()
            if not any(a.id == asset_id for a in rows):
                raise KeyError(asset_id)
            self._write([a for a in rows if a.id != asset_id])


def _default_assets() -> list[DigitalHumanAsset]:
    settings = get_settings()
    return [
        DigitalHumanAsset(
            id="default-voice",
            name="默认口播声线",
            provider="edge-tts",
            voice_id=settings.edge_tts_voice,
            avatar_name="Matrix 主播-A",
            opening_script="开场三秒先抛冲突，不念标题。",
            subtitle_style="逐字高亮，底部 8% 安全区",
            enabled=True,
        )
    ]


_store: DigitalHumanStore | None = None


def get_digital_human_store() -> DigitalHumanStore:
    global _store
    if _store is None:
        _store = DigitalHumanStore()
    return _store
