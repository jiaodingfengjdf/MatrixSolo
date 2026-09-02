from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from matrixsolo.config import Settings, get_settings


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}****{key[-4:]}"


class ModelCapability(str, Enum):
    """模型能力槽位：对应 PRD 模块 1 / 9 的 capability 字段."""

    TEXT = "text"
    VISION = "vision"
    IMAGE = "image"
    VIDEO = "video"
    TTS = "tts"


class AuthMethod(str, Enum):
    BEARER = "bearer"  # Authorization: Bearer <key>
    ANTHROPIC = "anthropic"  # x-api-key
    CUSTOM_HEADER = "custom_header"  # 自定义 header 名


class ModelProvider(BaseModel):
    """模型供应商：内置或自定义（OpenAI 兼容 / Anthropic / 自定义头）."""

    id: str
    name: str
    base_url: str = ""
    auth_method: AuthMethod = AuthMethod.BEARER
    api_key: str = ""  # 仅服务端存储，GET 返回脱敏
    api_key_header: str = ""  # auth_method == custom_header 时使用
    protocol: Literal["openai", "anthropic", "responses"] = "openai"  # 请求协议
    timeout: float = 120.0
    builtin: bool = False
    enabled: bool = True
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    def has_key(self) -> bool:
        return bool(self.api_key)

    def dump_admin(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["api_key_masked"] = _mask_key(self.api_key)
        data["has_key"] = self.has_key()
        data.pop("api_key", None)
        return data


class ModelSlot(BaseModel):
    """能力槽位：同一个 Provider 可挂多个 capability 的 model_id."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    provider_id: str
    model_id: str
    display_name: str = ""
    capability: list[ModelCapability] = Field(default_factory=lambda: [ModelCapability.TEXT])
    context_note: str = ""
    price_note: str = ""
    enabled: bool = True
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class ModelProviderCreate(BaseModel):
    id: str
    name: str
    base_url: str = ""
    auth_method: AuthMethod = AuthMethod.BEARER
    api_key: str = ""
    api_key_header: str = ""
    protocol: Literal["openai", "anthropic", "responses"] = "openai"
    timeout: float = 120.0
    default_model: str = ""  # 可选：添加 Provider 时顺便创建默认 text 槽位


class ModelProviderUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    auth_method: AuthMethod | None = None
    api_key: str | None = None
    api_key_header: str | None = None
    protocol: Literal["openai", "anthropic", "responses"] | None = None
    timeout: float | None = None
    enabled: bool | None = None


class ModelSlotCreate(BaseModel):
    provider_id: str
    model_id: str
    display_name: str = ""
    capability: list[ModelCapability] = Field(default_factory=lambda: [ModelCapability.TEXT])
    context_note: str = ""
    price_note: str = ""
    enabled: bool = True


class ModelSlotUpdate(BaseModel):
    model_id: str | None = None
    display_name: str | None = None
    capability: list[ModelCapability] | None = None
    context_note: str | None = None
    price_note: str | None = None
    enabled: bool | None = None


class ProbeResult(BaseModel):
    ok: bool
    provider_id: str
    model_id: str | None = None
    latency_ms: float | None = None
    error: str = ""


# 内置供应商（与 LLM_PROVIDER_CATALOG 对齐，读 settings 补齐密钥）
def builtin_providers(settings: Settings | None = None) -> list[ModelProvider]:
    # 每次全新解析 .env，避免长驻进程缓存旧值（改 .env 无需重启）
    s = settings if settings is not None else Settings()
    return [
        ModelProvider(
            id="grsai",
            name="Grsai",
            base_url=s.grsai_base_url,
            protocol="openai",
            auth_method=AuthMethod.BEARER,
            api_key=s.grsai_api_key,
            builtin=True,
        ),
        ModelProvider(
            id="openai",
            name="OpenAI",
            base_url=s.openai_base_url,
            protocol="openai",
            auth_method=AuthMethod.BEARER,
            api_key=s.openai_api_key,
            builtin=True,
        ),
        ModelProvider(
            id="anthropic",
            name="Anthropic",
            base_url=s.anthropic_base_url,
            protocol="anthropic",
            auth_method=AuthMethod.ANTHROPIC,
            api_key=s.anthropic_api_key,
            builtin=True,
        ),
        ModelProvider(
            id="deepseek",
            name="DeepSeek",
            base_url=s.deepseek_base_url,
            protocol="openai",
            auth_method=AuthMethod.BEARER,
            api_key=s.deepseek_api_key,
            builtin=True,
        ),
    ]


def builtin_slots(providers: list[ModelProvider]) -> list[ModelSlot]:
    slots: list[ModelSlot] = []
    defaults = {
        "grsai": ("gpt-5.4", "Grsai 文本", ["text", "vision"]),
        "openai": ("gpt-4o", "OpenAI 文本/视觉", ["text", "vision"]),
        "anthropic": ("claude-3-5-sonnet-20241022", "Anthropic 文本", ["text"]),
        "deepseek": ("deepseek-chat", "DeepSeek 文本", ["text"]),
    }
    for provider in providers:
        if not provider.builtin:
            continue
        model_id, name, caps = defaults.get(provider.id, (provider.id, provider.id, ["text"]))
        slots.append(
            ModelSlot(
                provider_id=provider.id,
                model_id=model_id,
                display_name=name,
                capability=[ModelCapability(c) for c in caps],
                enabled=True,
            )
        )
    return slots


class ModelStore:
    """模型中心持久化：自定义 Provider + 能力槽位，落盘 data/admin/model_providers.json."""

    def __init__(self) -> None:
        settings = get_settings()
        self.path = settings.data_dir / "admin" / "model_providers.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._ensure()

    def _ensure(self) -> None:
        if not self.path.exists():
            self._write(builtin_providers(), builtin_slots(builtin_providers()))
            return

    def _read(self) -> tuple[list[ModelProvider], list[ModelSlot]]:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        providers = [ModelProvider.model_validate(p) for p in raw.get("providers", [])]
        slots = [ModelSlot.model_validate(s) for s in raw.get("slots", [])]
        # 内置供应商始终以 .env 为准：base_url / api_key / 鉴权 / 协议
        builtins = {p.id: p for p in builtin_providers()}
        changed = False
        for provider in providers:
            if not provider.builtin:
                continue
            seed = builtins.get(provider.id)
            if not seed:
                continue
            if seed.base_url and provider.base_url != seed.base_url:
                provider.base_url = seed.base_url
                changed = True
            if provider.api_key != seed.api_key:
                provider.api_key = seed.api_key
                changed = True
            if provider.auth_method != seed.auth_method:
                provider.auth_method = seed.auth_method
                changed = True
            if provider.protocol != seed.protocol:
                provider.protocol = seed.protocol
                changed = True
        if changed:
            # 把 .env 最新值回写注册表，避免磁盘残留旧空密钥
            try:
                self._write(providers, slots)
            except OSError:
                pass
        return providers, slots

    def _write(
        self,
        providers: list[ModelProvider],
        slots: list[ModelSlot],
    ) -> None:
        payload = {
            "providers": [p.model_dump(mode="json") for p in providers],
            "slots": [s.model_dump(mode="json") for s in slots],
        }
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list_providers(self) -> list[ModelProvider]:
        with self._lock:
            providers, _ = self._read()
            return providers

    def list_slots(self) -> list[ModelSlot]:
        with self._lock:
            _, slots = self._read()
            return slots

    def get_provider(self, provider_id: str) -> ModelProvider | None:
        with self._lock:
            providers, _ = self._read()
            return next((p for p in providers if p.id == provider_id), None)

    def default_provider_id(self) -> str:
        return Settings().llm_default_provider or "grsai"

    def create_provider(self, body: ModelProviderCreate) -> ModelProvider:
        with self._lock:
            providers, slots = self._read()
            if any(p.id == body.id for p in providers):
                raise ValueError(f"provider id 已存在: {body.id}")
            data = body.model_dump(exclude={"default_model"})
            provider = ModelProvider(**data)
            provider.builtin = False
            providers.append(provider)
            default_model = (body.default_model or "").strip()
            if default_model:
                slots.append(
                    ModelSlot(
                        provider_id=provider.id,
                        model_id=default_model,
                        display_name=default_model,
                        capability=[ModelCapability.TEXT],
                        enabled=True,
                    )
                )
            self._write(providers, slots)
            return provider

    def update_provider(self, provider_id: str, body: ModelProviderUpdate) -> ModelProvider:
        with self._lock:
            providers, slots = self._read()
            index = next((i for i, p in enumerate(providers) if p.id == provider_id), None)
            if index is None:
                raise KeyError(provider_id)
            current = providers[index]
            data = current.model_dump()
            for field, value in body.model_dump(exclude_unset=True).items():
                if field == "api_key":
                    # 未改密钥则不覆盖
                    if value:
                        data[field] = value
                elif value is not None:
                    data[field] = value
            data["updated_at"] = _utcnow().isoformat()
            updated = ModelProvider.model_validate(data)
            providers[index] = updated
            self._write(providers, slots)
            return updated

    def delete_provider(self, provider_id: str) -> None:
        with self._lock:
            providers, slots = self._read()
            provider = next((p for p in providers if p.id == provider_id), None)
            if provider is None:
                raise KeyError(provider_id)
            if provider.builtin:
                raise ValueError("内置 Provider 不可删除，可停用")
            providers = [p for p in providers if p.id != provider_id]
            slots = [s for s in slots if s.provider_id != provider_id]
            self._write(providers, slots)

    def create_slot(self, body: ModelSlotCreate) -> ModelSlot:
        with self._lock:
            providers, slots = self._read()
            if not any(p.id == body.provider_id for p in providers):
                raise KeyError(body.provider_id)
            slot = ModelSlot(**body.model_dump())
            if not slot.capability:
                slot.capability = [ModelCapability.TEXT]
            slots.append(slot)
            self._write(providers, slots)
            return slot

    def update_slot(self, slot_id: str, body: ModelSlotUpdate) -> ModelSlot:
        with self._lock:
            providers, slots = self._read()
            index = next((i for i, s in enumerate(slots) if s.id == slot_id), None)
            if index is None:
                raise KeyError(slot_id)
            current = slots[index]
            data = current.model_dump()
            for field, value in body.model_dump(exclude_unset=True).items():
                if value is not None:
                    data[field] = value
            if not data.get("capability"):
                data["capability"] = [ModelCapability.TEXT]
            data["updated_at"] = _utcnow().isoformat()
            updated = ModelSlot.model_validate(data)
            slots[index] = updated
            self._write(providers, slots)
            return updated

    def delete_slot(self, slot_id: str) -> None:
        with self._lock:
            providers, slots = self._read()
            if not any(s.id == slot_id for s in slots):
                raise KeyError(slot_id)
            slots = [s for s in slots if s.id != slot_id]
            self._write(providers, slots)

    def supports_capability(self, provider_id: str, capability: ModelCapability) -> bool:
        with self._lock:
            _, slots = self._read()
            return any(
                s.provider_id == provider_id and s.enabled and capability in s.capability
                for s in slots
            )

    def resolve_slot(
        self,
        provider_id: str,
        model_id: str | None = None,
        capability: ModelCapability | None = None,
    ) -> ModelSlot | None:
        """按 provider + model / capability 解析槽位."""
        with self._lock:
            _, slots = self._read()
            candidates = [s for s in slots if s.provider_id == provider_id and s.enabled]
            if model_id:
                exact = next((s for s in candidates if s.model_id == model_id), None)
                if exact:
                    return exact
            if capability:
                cap = next((s for s in candidates if capability in s.capability), None)
                if cap:
                    return cap
            return candidates[0] if candidates else None


_store: ModelStore | None = None


def get_model_store() -> ModelStore:
    global _store
    if _store is None:
        _store = ModelStore()
    return _store
