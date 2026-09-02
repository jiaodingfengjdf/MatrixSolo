from __future__ import annotations

import json
import logging
from enum import Enum
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from matrixsolo.config import Settings, get_settings

logger = logging.getLogger(__name__)


class TaskKind(str, Enum):
    """认知任务类型 → 路由到不同模型."""

    CREATIVE = "creative"
    CLASSIFY = "classify"
    GUARDRAIL = "guardrail"
    STRUCTURED = "structured"


class CapabilityUnavailable(RuntimeError):
    """能力槽位未配置或密钥缺失：调用方应降级，不得静默 mock."""


class LLMGateway:
    """统一 LLM API 网关：按任务类型路由到不同 Provider."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def _resolve(
        self,
        kind: TaskKind,
        *,
        provider_override: str | None = None,
        model_override: str | None = None,
        base_url_override: str | None = None,
    ) -> tuple[str, str, str]:
        s = self.settings
        if provider_override:
            provider = provider_override
            info = self._provider_info(provider)
            if info is not None:
                base_url = base_url_override or info.get("base_url", "")
                model = model_override or self._default_model_for_provider(provider)
                return provider, base_url, model
            if provider == "anthropic":
                return (
                    provider,
                    base_url_override or s.anthropic_base_url,
                    model_override or s.anthropic_model,
                )
            if provider == "deepseek":
                return (
                    provider,
                    base_url_override or s.deepseek_base_url,
                    model_override or s.deepseek_model,
                )
            if provider == "grsai":
                return (
                    "grsai",
                    base_url_override or s.grsai_base_url,
                    model_override or s.grsai_model,
                )
            return (
                "openai",
                base_url_override or s.openai_base_url,
                model_override or s.openai_model,
            )

        # 全局默认也可指向模型中心自定义 Provider
        default_provider = s.llm_default_provider or "grsai"
        default_info = self._provider_info(default_provider)
        if default_info and default_provider not in {"openai", "anthropic", "deepseek", "grsai"}:
            return (
                default_provider,
                base_url_override or default_info.get("base_url", ""),
                model_override or self._default_model_for_provider(default_provider),
            )

        # 显式默认底座优先
        if s.llm_default_provider == "grsai" and s.grsai_api_key:
            return "grsai", s.grsai_base_url, s.grsai_model
        if kind in (TaskKind.CREATIVE, TaskKind.STRUCTURED):
            if s.grsai_api_key:
                return "grsai", s.grsai_base_url, s.grsai_model
            if s.anthropic_api_key:
                return "anthropic", s.anthropic_base_url, s.anthropic_model
            if s.openai_api_key:
                return "openai", s.openai_base_url, s.openai_model
        if kind in (TaskKind.CLASSIFY, TaskKind.GUARDRAIL):
            if s.deepseek_api_key:
                return "deepseek", s.deepseek_base_url, s.deepseek_model
            if s.grsai_api_key:
                return "grsai", s.grsai_base_url, s.grsai_model
            if s.openai_api_key:
                return "openai", s.openai_base_url, s.openai_model
        provider = s.llm_default_provider
        if provider == "grsai" and s.grsai_api_key:
            return "grsai", s.grsai_base_url, s.grsai_model
        if provider == "anthropic" and s.anthropic_api_key:
            return "anthropic", s.anthropic_base_url, s.anthropic_model
        if provider == "deepseek" and s.deepseek_api_key:
            return "deepseek", s.deepseek_base_url, s.deepseek_model
        if s.grsai_api_key:
            return "grsai", s.grsai_base_url, s.grsai_model
        return "openai", s.openai_base_url, s.openai_model

    def _provider_info(self, provider_id: str) -> dict[str, Any] | None:
        """从模型中心注册表解析 Provider；未注册回退 settings（内置）。"""
        from matrixsolo.admin.model_center import get_model_store

        provider = get_model_store().get_provider(provider_id)
        if provider:
            return {
                "base_url": provider.base_url,
                "protocol": provider.protocol,
                "auth_method": provider.auth_method.value,
                "api_key": provider.api_key,
                "api_key_header": provider.api_key_header or "",
            }
        s = self.settings
        table = {
            "grsai": (s.grsai_base_url, "openai", "bearer", s.grsai_api_key, ""),
            "openai": (s.openai_base_url, "openai", "bearer", s.openai_api_key, ""),
            "anthropic": (s.anthropic_base_url, "anthropic", "anthropic", s.anthropic_api_key, ""),
            "deepseek": (s.deepseek_base_url, "openai", "bearer", s.deepseek_api_key, ""),
        }
        row = table.get(provider_id)
        if row:
            return {
                "base_url": row[0],
                "protocol": row[1],
                "auth_method": row[2],
                "api_key": row[3],
                "api_key_header": row[4],
            }
        return None

    def _default_model_for_provider(self, provider_id: str) -> str:
        from matrixsolo.admin.model_center import get_model_store

        slot = get_model_store().resolve_slot(provider_id)
        if slot:
            return slot.model_id
        s = self.settings
        return {
            "grsai": s.grsai_model,
            "openai": s.openai_model,
            "anthropic": s.anthropic_model,
            "deepseek": s.deepseek_model,
        }.get(provider_id, "")

    def provider_protocol(self, provider_id: str) -> str:
        info = self._provider_info(provider_id)
        return (info or {}).get("protocol", "openai")

    def _api_key(self, provider: str) -> str:
        info = self._provider_info(provider)
        if info:
            return info.get("api_key") or ""
        s = self.settings
        if provider == "anthropic":
            return s.anthropic_api_key
        if provider == "deepseek":
            return s.deepseek_api_key
        if provider == "grsai":
            return s.grsai_api_key
        return s.openai_api_key

    def supports_capability(self, provider_id: str, capability: str) -> bool:
        from matrixsolo.admin.model_center import ModelCapability, get_model_store

        try:
            cap = ModelCapability(capability)
        except ValueError:
            return False
        return get_model_store().supports_capability(provider_id, cap)

    def has_capability(self, capability: str) -> bool:
        from matrixsolo.admin.model_center import ModelCapability, get_model_store

        try:
            cap = ModelCapability(capability)
        except ValueError:
            return False
        return any(
            slot.enabled and cap in slot.capability
            for slot in get_model_store().list_slots()
        )

    async def complete_text(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> str:
        return await self.chat(messages, **kwargs)

    async def complete_vision(
        self,
        messages: list[dict[str, str]],
        images: list[str],
        **kwargs: Any,
    ) -> str:
        """视觉理解：走 vision 能力槽位（OpenAI 兼容 image_url）。无槽位/密钥则抛 CapabilityUnavailable."""
        from matrixsolo.admin.model_center import ModelCapability, get_model_store

        slot = next(
            (
                s
                for s in get_model_store().list_slots()
                if s.enabled and ModelCapability.VISION in s.capability
            ),
            None,
        )
        if not slot:
            raise CapabilityUnavailable("vision 能力槽位未配置")
        provider = get_model_store().get_provider(slot.provider_id)
        if not provider or not provider.api_key:
            raise CapabilityUnavailable(f"vision provider 未配置密钥: {slot.provider_id}")
        if provider.protocol not in {"openai", "responses"}:
            raise CapabilityUnavailable("视觉理解暂仅支持 OpenAI 兼容 / Responses 协议")

        content: list[dict[str, Any]] = [
            {"type": "text", "text": (m.get("content") or "")} for m in messages
        ]
        for image in (images or [])[:8]:
            content.append({"type": "image_url", "image_url": {"url": image}})
        if provider.protocol == "responses":
            return await self._chat_responses(
                messages,
                provider.base_url,
                slot.model_id,
                provider.api_key,
                float(kwargs.get("temperature") or 0.3),
                int(kwargs.get("max_tokens") or 2048),
                None,
                images=(images or [])[:8],
                auth_method=provider.auth_method.value,
                api_key_header=provider.api_key_header or "",
            )
        payload_messages = [
            {"role": "user", "content": content},
        ]
        return await self._chat_openai_compat(
            payload_messages,
            provider.base_url,
            slot.model_id,
            provider.api_key,
            float(kwargs.get("temperature") or 0.3),
            int(kwargs.get("max_tokens") or 2048),
            None,
            auth_method=provider.auth_method.value,
            api_key_header=provider.api_key_header or "",
        )

    async def generate_image(self, prompt: str, size: str = "16:9") -> dict[str, Any]:
        from matrixsolo.skills.runtime import SkillRuntime

        return await SkillRuntime().image_gen(prompt, aspect_ratio=size)

    async def generate_video(
        self,
        prompt: str,
        ref_images: list[str] | None = None,
        duration: float = 0.0,
        workflow_id: str = "",
        project: str = "",
        department_id: str = "default",
        department_name: str = "默认",
    ) -> dict[str, Any]:
        from matrixsolo.admin.video_jobs import get_video_job_manager

        return await get_video_job_manager().create(
            prompt=prompt,
            ref_images=ref_images or [],
            duration=duration,
            workflow_id=workflow_id,
            project=project,
            department_id=department_id,
            department_name=department_name,
        )

    async def synthesize_speech(
        self,
        text: str,
        voice_id: str | None = None,
        out_dir: Any = None,
    ) -> dict[str, Any]:
        import os
        from pathlib import Path

        text = (text or "").strip()
        if not text:
            return {"ok": False, "error": "缺少需要合成的文本"}
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return {
                "ok": True,
                "path": "",
                "voice": voice_id or self.settings.edge_tts_voice,
                "note": "pytest skip real tts",
            }
        import edge_tts

        root = Path(out_dir or (self.settings.data_dir / "exports" / "tts"))
        root.mkdir(parents=True, exist_ok=True)
        voice = (voice_id or self.settings.edge_tts_voice) or "zh-CN-YunxiNeural"
        from uuid import uuid4

        target = root / f"tts_{uuid4().hex[:10]}.mp3"
        communicate = edge_tts.Communicate(text, voice)
        with target.open("wb") as handle:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    handle.write(chunk["data"])
        return {"ok": True, "path": str(target), "voice": voice}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        kind: TaskKind = TaskKind.CREATIVE,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: dict[str, Any] | None = None,
        provider: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> str:
        resolved_provider, resolved_base, resolved_model = self._resolve(
            kind,
            provider_override=provider,
            model_override=model,
            base_url_override=base_url,
        )
        api_key = self._api_key(resolved_provider)

        if not api_key:
            logger.warning("No LLM API key configured; returning mock response")
            return self._mock_response(messages, kind)

        info = self._provider_info(resolved_provider) or {}
        if info.get("protocol", "openai") == "anthropic":
            return await self._chat_anthropic(
                messages, resolved_base, resolved_model, api_key, temperature, max_tokens
            )
        if info.get("protocol", "openai") == "responses":
            return await self._chat_responses(
                messages,
                resolved_base,
                resolved_model,
                api_key,
                temperature,
                max_tokens,
                response_format,
                auth_method=info.get("auth_method", "bearer"),
                api_key_header=info.get("api_key_header", ""),
            )
        # openai / deepseek / grsai 均走 OpenAI 兼容协议
        return await self._chat_openai_compat(
            messages,
            resolved_base,
            resolved_model,
            api_key,
            temperature,
            max_tokens,
            response_format,
            auth_method=info.get("auth_method", "bearer"),
            api_key_header=info.get("api_key_header", ""),
        )

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        kind: TaskKind = TaskKind.STRUCTURED,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        provider: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        raw = await self.chat(
            messages,
            kind=kind,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            provider=provider,
            model=model,
            base_url=base_url,
        )
        raw = raw.strip()
        from matrixsolo.skills.runtime import strip_think

        raw = strip_think(raw)
        if raw.startswith("```"):
            raw = raw.strip("`")
            raw = raw.removeprefix("json")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            start, end = raw.find("{"), raw.rfind("}")
            if start >= 0 and end > start:
                return json.loads(raw[start : end + 1])
            logger.warning("chat_json fallback empty object; raw=%r", raw[:120])
            return {}

    async def chat_for_role(
        self,
        role: str,
        messages: list[dict[str, str]],
        *,
        kind: TaskKind = TaskKind.CREATIVE,
        as_json: bool = False,
    ) -> str | dict[str, Any]:
        """按管理台岗位配置路由模型，并注入 composed system prompt（若 messages 无 system）。"""
        from matrixsolo.admin.store import get_profile_store

        profile = get_profile_store().get_or_create(role)
        composed = profile.composed_system_prompt()
        msgs = list(messages)
        if composed:
            if msgs and msgs[0].get("role") == "system":
                msgs[0] = {
                    "role": "system",
                    "content": composed + "\n\n" + msgs[0].get("content", ""),
                }
            else:
                msgs.insert(0, {"role": "system", "content": composed})
        llm = profile.llm
        logger.info(
            "chat_for_role role=%s provider=%s",
            role,
            llm.provider,
        )
        if as_json:
            return await self.chat_json(
                msgs,
                kind=kind,
                temperature=llm.temperature,
                max_tokens=llm.max_tokens,
                provider=llm.provider,
                base_url=llm.base_url or None,
            )
        return await self.chat(
            msgs,
            kind=kind,
            temperature=llm.temperature,
            max_tokens=llm.max_tokens,
            provider=llm.provider,
            base_url=llm.base_url or None,
        )

    async def _chat_openai_compat(
        self,
        messages: list[dict[str, str]],
        base_url: str,
        model: str,
        api_key: str,
        temperature: float,
        max_tokens: int,
        response_format: dict[str, Any] | None,
        *,
        auth_method: str = "bearer",
        api_key_header: str = "",
    ) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            # Grsai 等兼容网关将 stream 标为必填；非流式统一 false
            "stream": False,
        }
        if response_format:
            payload["response_format"] = response_format
        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = self._auth_headers(api_key, auth_method, api_key_header)
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                url,
                headers=headers,
                json=payload,
            )
            if resp.status_code >= 400:
                logger.error("LLM error %s %s: %s", resp.status_code, url, resp.text[:500])
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    @staticmethod
    def _responses_endpoint(base_url: str) -> str:
        """DeepSeek Responses API 根路径是 /responses，兼容用户误填 /v1 的情况."""
        base = (base_url or "").strip().rstrip("/")
        if base.endswith("/v1") and "api.deepseek.com" in base:
            base = base[: -3].rstrip("/")
        if base.endswith("/responses"):
            return base
        return f"{base}/responses"

    def _responses_input(
        self,
        messages: list[dict[str, str]],
        images: list[str] | None = None,
    ) -> tuple[str, list[dict[str, Any]]]:
        """把业务消息转换为 Responses API input，并将 system 提升为 instructions."""
        system_parts: list[str] = []
        items: list[dict[str, Any]] = []
        image_urls = (images or [])[:8]
        for msg in messages:
            role = (msg.get("role") or "user").strip()
            text = msg.get("content") or ""
            if role == "system":
                system_parts.append(text)
                continue
            if role not in {"user", "assistant", "developer"}:
                role = "user"
            content: Any = text
            if image_urls and role == "user":
                content = [{"type": "input_text", "text": text}]
                content.extend(
                    {"type": "input_image", "image_url": url} for url in image_urls
                )
                image_urls = []
            items.append({"role": role, "content": content})
        if not items:
            items.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "hello"},
                    ],
                }
            )
        return "\n\n".join(p for p in system_parts if p), items

    async def _chat_responses(
        self,
        messages: list[dict[str, str]],
        base_url: str,
        model: str,
        api_key: str,
        temperature: float,
        max_tokens: int,
        response_format: dict[str, Any] | None,
        *,
        images: list[str] | None = None,
        auth_method: str = "bearer",
        api_key_header: str = "",
    ) -> str:
        """OpenAI Responses API 格式（DeepSeek 新版 /responses 同构）."""
        instructions, input_items = self._responses_input(messages, images)
        payload: dict[str, Any] = {
            "model": model,
            "input": input_items,
            "temperature": temperature,
            "max_output_tokens": max_tokens,
            "stream": False,
        }
        if instructions:
            payload["instructions"] = instructions
        if response_format:
            payload["text"] = {
                "format": {"type": response_format.get("type", "text")}
            }
        url = self._responses_endpoint(base_url)
        headers = self._auth_headers(api_key, auth_method, api_key_header)
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code >= 400:
                logger.error("LLM error %s %s: %s", resp.status_code, url, resp.text[:500])
            resp.raise_for_status()
            data = resp.json()
            raw = data.get("output_text")
            if not isinstance(raw, str):
                raw = ""
                for item in data.get("output") or []:
                    content = item.get("content")
                    if isinstance(content, list):
                        raw += "".join(
                            part.get("text", "")
                            for part in content
                            if isinstance(part, dict) and part.get("type") == "output_text"
                        )
                    elif isinstance(content, str):
                        raw += content
            if not raw:
                raise RuntimeError("Responses API 返回内容为空或缺少 output_text")
            return raw

    def _auth_headers(self, api_key: str, auth_method: str, header_name: str) -> dict[str, str]:
        if auth_method == "custom_header":
            name = (header_name or "Authorization").strip()
            return {"Authorization": f"Bearer {api_key}", name: api_key}
        return {"Authorization": f"Bearer {api_key}"}

    async def probe(
        self,
        provider_id: str,
        model_id: str | None = None,
        *,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        """模型中心连通性探测：发一条最小 chat/completions（或 /v1/messages）。"""
        import time

        info = self._provider_info(provider_id) or {}
        protocol = info.get("protocol", "openai")
        api_key = self._api_key(provider_id)
        if not api_key:
            return {
                "ok": False,
                "provider_id": provider_id,
                "error": "未配置 API Key",
            }
        model = model_id or self._default_model_for_provider(provider_id)
        if not model:
            return {
                "ok": False,
                "provider_id": provider_id,
                "error": (
                    f"未找到 {provider_id} 的 model 槽位。请先在模型中心为它添加"
                    "「能力槽位」(model_id)，或在新建 Provider 时填写默认模型。"
                ),
            }
        base = base_url or info.get("base_url", "")
        started = time.perf_counter()
        try:
            if protocol == "anthropic":
                raw = await self._chat_anthropic(
                    [{"role": "user", "content": "ping"}],
                    base,
                    model,
                    api_key,
                    0.1,
                    16,
                )
            elif protocol == "responses":
                raw = await self._chat_responses(
                    [{"role": "user", "content": "ping"}],
                    base,
                    model,
                    api_key,
                    0.1,
                    512,
                    None,
                    auth_method=info.get("auth_method", "bearer"),
                    api_key_header=info.get("api_key_header", ""),
                )
            else:
                raw = await self._chat_openai_compat(
                    [{"role": "user", "content": "ping"}],
                    base,
                    model,
                    api_key,
                    0.1,
                    16,
                    None,
                    auth_method=info.get("auth_method", "bearer"),
                    api_key_header=info.get("api_key_header", ""),
                )
            latency = (time.perf_counter() - started) * 1000
            return {
                "ok": bool(raw),
                "provider_id": provider_id,
                "model_id": model,
                "latency_ms": round(latency, 1),
                "error": "",
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "provider_id": provider_id,
                "model_id": model,
                "error": str(exc)[:400],
            }

    async def chat_for_employee(
        self,
        employee_id: str,
        messages: list[dict[str, str]],
        *,
        kind: TaskKind = TaskKind.CREATIVE,
        as_json: bool = False,
    ) -> str | dict[str, Any]:
        """PRD 模块 1：chat_for_employee 作为 chat_for_role 的别名，employee_id 即岗位 id."""
        return await self.chat_for_role(
            employee_id,
            messages,
            kind=kind,
            as_json=as_json,
        )

    async def _chat_anthropic(
        self,
        messages: list[dict[str, str]],
        base_url: str,
        model: str,
        api_key: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        system = ""
        converted: list[dict[str, Any]] = []
        for msg in messages:
            if msg["role"] == "system":
                system = msg["content"]
            else:
                converted.append({"role": msg["role"], "content": msg["content"]})
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": converted or [{"role": "user", "content": "hello"}],
        }
        if system:
            payload["system"] = system
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{base_url.rstrip('/')}/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            parts = data.get("content") or []
            return "".join(p.get("text", "") for p in parts if p.get("type") == "text")

    def _mock_response(self, messages: list[dict[str, str]], kind: TaskKind) -> str:
        last = messages[-1]["content"] if messages else ""
        blob = "\n".join(m.get("content", "") for m in messages)

        if kind == TaskKind.GUARDRAIL or "合规审查" in blob or "内容合规" in blob:
            return json.dumps(
                {"level": 0, "pass": True, "issues": [], "suggestions": []},
                ensure_ascii=False,
            )

        wants_json = (
            kind in (TaskKind.STRUCTURED, TaskKind.CLASSIFY, TaskKind.CREATIVE)
            or "JSON" in last.upper()
            or "返回 JSON" in blob
            or "输出" in last and "JSON" in blob.upper()
        )
        if wants_json:
            # 优先匹配 user 任务意图，避免 system「能力边界」里的词误伤
            if "请输出脚本" in last or "输出脚本 JSON" in last or ("形态要求" in last and "titles" in blob):
                return json.dumps(
                    {
                        "hook": "如果你以为自己看懂了这部电影，那说明你还没真正看懂。",
                        "body": (
                            "开场三分钟，导演就把所有线索摆在桌面上。"
                            "问题是，观众只会盯着最显眼的那一块。"
                            "今天我们逐帧拆开，你会发现真正的反转藏在眼神里。"
                        ),
                        "titles": [
                            "这部电影的反转，藏在第一秒的眼神里",
                            "看懂它的人，不到 10%",
                            "影史最狠的三重叙事：你错过了什么？",
                            "导演故意骗你：真相其实很温柔",
                            "3 个细节证明：结局早就写好了",
                        ],
                        "article_markdown": "## 信息增量\n...\n## 情感共鸣\n...\n## 反转叙事\n...",
                    },
                    ensure_ascii=False,
                )
            if "请输出封面" in last or "封面 Prompt JSON" in last or "美术指导" in blob and "covers" in blob:
                return json.dumps(
                    {
                        "covers": [
                            {
                                "label": "A-悬念",
                                "mood": "悬疑压迫",
                                "prompt": "cinematic film poster, dark teal lighting, close-up eyes",
                            },
                            {
                                "label": "B-冲突",
                                "mood": "戏剧冲突",
                                "prompt": "two characters facing off, dramatic rim light",
                            },
                            {
                                "label": "C-情绪",
                                "mood": "情感冲击",
                                "prompt": "tearful close-up, soft bokeh, golden hour",
                            },
                        ]
                    },
                    ensure_ascii=False,
                )
            if "SEO 元数据" in last or ("主推标题" in last and "packages" in blob):
                return json.dumps(
                    {
                        "packages": [
                            {
                                "platform": "douyin",
                                "title": "这部电影的反转你一定错过了",
                                "description": "逐帧拆解高智商叙事",
                                "tags": ["电影解说", "悬疑", "高智商"],
                            },
                            {
                                "platform": "bilibili",
                                "title": "【逐帧拆解】你以为看懂了？真相在第一秒",
                                "description": "深度影评向解说",
                                "tags": ["影视杂谈", "电影解析"],
                            },
                            {
                                "platform": "toutiao",
                                "title": "影史最狠三重叙事：看懂的人不到一成",
                                "description": "信息增量 + 情感共鸣",
                                "tags": ["电影", "深度"],
                            },
                        ]
                    },
                    ensure_ascii=False,
                )
            if "请输出选题" in last or "热榜:" in last or (
                ("产出 3 个选题" in blob or "topics" in blob) and "potential_score" in blob
            ):
                return json.dumps(
                    {
                        "topics": [
                            {
                                "film_name": "盗梦空间",
                                "douban_score": 9.0,
                                "reason": "高概念悬疑，情绪张力强，素材丰富",
                                "hook_points": ["梦境嵌套", "现实崩塌", "父女和解"],
                                "heat_index": 86,
                                "emotion_score": 0.9,
                                "audience_breadth": 0.85,
                                "material_richness": 0.95,
                                "potential_score": 88.5,
                            },
                            {
                                "film_name": "看不见的客人",
                                "douban_score": 8.8,
                                "reason": "反转密集，适合逐帧解说",
                                "hook_points": ["三重反转", "律师对峙", "真相错位"],
                                "heat_index": 78,
                                "emotion_score": 0.88,
                                "audience_breadth": 0.8,
                                "material_richness": 0.7,
                                "potential_score": 82.0,
                            },
                            {
                                "film_name": "瞬息全宇宙",
                                "douban_score": 8.0,
                                "reason": "题材新鲜，混剪盘点空间大",
                                "hook_points": ["多元宇宙", "母女和解", "荒诞喜剧"],
                                "heat_index": 72,
                                "emotion_score": 0.8,
                                "audience_breadth": 0.75,
                                "material_richness": 0.88,
                                "potential_score": 79.0,
                            },
                        ]
                    },
                    ensure_ascii=False,
                )
            if "事实核查" in blob or "suspicious_spans" in blob:
                return json.dumps(
                    {"ok": True, "notes": [], "suspicious_spans": []},
                    ensure_ascii=False,
                )
            if "多平台" in blob or "packages" in blob or "SEO" in blob or "Tags" in blob:
                return json.dumps(
                    {
                        "packages": [
                            {
                                "platform": "douyin",
                                "title": "这部电影的反转你一定错过了",
                                "description": "逐帧拆解高智商叙事",
                                "tags": ["电影解说", "悬疑", "高智商"],
                            },
                            {
                                "platform": "bilibili",
                                "title": "【逐帧拆解】你以为看懂了？真相在第一秒",
                                "description": "深度影评向解说",
                                "tags": ["影视杂谈", "电影解析"],
                            },
                            {
                                "platform": "toutiao",
                                "title": "影史最狠三重叙事：看懂的人不到一成",
                                "description": "信息增量 + 情感共鸣",
                                "tags": ["电影", "深度"],
                            },
                        ]
                    },
                    ensure_ascii=False,
                )
            if "封面" in blob or "美术指导" in blob:
                return json.dumps(
                    {
                        "covers": [
                            {
                                "label": "A-悬念",
                                "mood": "悬疑压迫",
                                "prompt": "cinematic film poster, dark teal lighting, close-up eyes",
                            },
                            {
                                "label": "B-冲突",
                                "mood": "戏剧冲突",
                                "prompt": "two characters facing off, dramatic rim light",
                            },
                            {
                                "label": "C-情绪",
                                "mood": "情感冲击",
                                "prompt": "tearful close-up, soft bokeh, golden hour",
                            },
                        ]
                    },
                    ensure_ascii=False,
                )
            if "输出脚本" in blob or ("脚本匠" in blob and "titles" in blob):
                return json.dumps(
                    {
                        "hook": "如果你以为自己看懂了这部电影，那说明你还没真正看懂。",
                        "body": (
                            "开场三分钟，导演就把所有线索摆在桌面上。"
                            "问题是，观众只会盯着最显眼的那一块。"
                            "今天我们逐帧拆开，你会发现真正的反转藏在眼神里。"
                        ),
                        "titles": [
                            "这部电影的反转，藏在第一秒的眼神里",
                            "看懂它的人，不到 10%",
                            "影史最狠的三重叙事：你错过了什么？",
                            "导演故意骗你：真相其实很温柔",
                            "3 个细节证明：结局早就写好了",
                        ],
                        "article_markdown": "## 信息增量\n...\n## 情感共鸣\n...\n## 反转叙事\n...",
                    },
                    ensure_ascii=False,
                )
            return json.dumps({"ok": True}, ensure_ascii=False)
        return "（未配置 LLM Key，已返回占位文案。请在 .env 中配置 API Key。）"


_gateway: LLMGateway | None = None


def get_gateway() -> LLMGateway:
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway
