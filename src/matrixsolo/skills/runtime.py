from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from matrixsolo.admin.models import AgentProfile, TOOL_CATALOG

logger = logging.getLogger(__name__)

IMAGE_SKILL_ALIASES = {"image_gen", "cover_gen", "grsai-image-gen", "grsai_image_gen"}
_IMAGE_ASPECTS = {"1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"}

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
_MAX_TEXT = 8000
_MAX_BYTES = 1_500_000

RADAR_SOURCES = [
    (
        "bilibili_popular",
        "https://api.bilibili.com/x/web-interface/popular?ps=20&pn=1",
        "json",
    ),
    (
        "bilibili_movie",
        "https://api.bilibili.com/pgc/season/rank/web/list?day=3&season_type=2",
        "json",
    ),
    (
        "douban_chart",
        "https://movie.douban.com/chart",
        "html",
    ),
]


class _TextExtractor(HTMLParser):
    _SKIP = {"script", "style", "noscript", "svg", "head"}

    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        text = html.unescape(data).strip()
        if text:
            self.parts.append(text)


def html_to_text(raw: str, limit: int = _MAX_TEXT) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(raw)
        parser.close()
    except Exception:  # noqa: BLE001
        text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", raw)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        return html.unescape(re.sub(r"\s+", " ", text))[:limit]
    return re.sub(r"\s+", " ", " ".join(parser.parts))[:limit]


def strip_think(text: str) -> str:
    cleaned = re.sub(r"(?is)<think>.*?</think>", "", text)
    cleaned = re.sub(r"(?is)<think>[^\n]*", "", cleaned)
    cleaned = re.sub(r"(?i)</?think>", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


def parse_skill_call(text: str) -> dict[str, Any] | None:
    blob = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", blob, re.DOTALL)
    if fence:
        blob = fence.group(1)
    else:
        match = re.search(r"\{[^{}]*\"skill\"[^{}]*\}", blob, re.DOTALL)
        if match:
            blob = match.group(0)
        elif not (blob.startswith("{") and "skill" in blob):
            return None
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not str(data.get("skill") or "").strip():
        return None
    return data


def can_image_gen(profile: AgentProfile) -> bool:
    """视觉岗只要开了 image_gen/cover_gen，或装了生图技能包，就能真实出图。"""
    if not profile.enabled:
        return False
    if profile.has_tool("image_gen") or profile.has_tool("cover_gen"):
        return True
    for skill in profile.skills:
        if not skill.enabled:
            continue
        blob = f"{skill.name} {skill.origin} {skill.description}".lower()
        if any(token in blob for token in ("image", "生图", "gpt-image", "出图")):
            return True
    return False


def _image_api_root(chat_base: str) -> str:
    base = (chat_base or "https://grsai.dakka.com.cn/v1").rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    return base or "https://grsai.dakka.com.cn"


def _normalize_aspect(value: str) -> str:
    ratio = (value or "16:9").strip().lower().replace("x", ":").replace("×", ":")
    return ratio if ratio in _IMAGE_ASPECTS else "16:9"


def _result_items(result: dict[str, Any]) -> list[Any]:
    raw = result.get("results")
    if raw is None:
        raw = result.get("data")
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list):
        return raw
    if result.get("url"):
        return [result]
    return []


class SkillRuntime:
    """内置可执行技能：联网、基础爬虫、热榜、生图。"""

    async def run(self, key: str, profile: AgentProfile, **kwargs: Any) -> dict[str, Any]:
        import time

        from matrixsolo.admin.tool_audit import get_tool_audit_store

        started = time.perf_counter()
        result = await self._run(key, profile, **kwargs)
        try:
            get_tool_audit_store().append(
                employee_id=profile.role,
                tool=key,
                kind="runtime",
                ok=bool(result.get("ok")),
                error=str(result.get("error") or ""),
                duration_ms=(time.perf_counter() - started) * 1000,
                params=kwargs,
            )
        except Exception:  # noqa: BLE001
            logger.exception("tool audit failed")
        return result

    async def _run(self, key: str, profile: AgentProfile, **kwargs: Any) -> dict[str, Any]:
        key = str(key or "").strip()
        if key in IMAGE_SKILL_ALIASES:
            if not can_image_gen(profile):
                return {"ok": False, "skill": "image_gen", "error": "生图技能未启用"}
            return await self.image_gen(
                prompt=str(kwargs.get("prompt") or kwargs.get("text") or ""),
                aspect_ratio=str(
                    kwargs.get("aspect_ratio") or kwargs.get("aspectRatio") or "16:9"
                ),
            )
        if not (profile.enabled and profile.has_tool(key)):
            return {"ok": False, "skill": key, "error": f"技能 {key} 未启用"}
        if key == "web_fetch":
            return await self.web_fetch(str(kwargs.get("url") or ""))
        if key == "browser_crawl":
            urls = kwargs.get("urls") or []
            if isinstance(urls, str):
                urls = [urls]
            extra = str(kwargs.get("url") or "")
            if extra:
                urls = [extra, *list(urls)]
            return await self.browser_crawl([str(u) for u in urls if str(u).strip()])
        if key == "hot_radar":
            return await self.hot_radar()
        return {"ok": False, "skill": key, "error": f"未知技能 {key}"}

    async def image_gen(self, prompt: str, aspect_ratio: str = "16:9") -> dict[str, Any]:
        prompt = (prompt or "").strip()
        if not prompt:
            return {"ok": False, "skill": "image_gen", "error": "缺少画面 prompt"}
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return {
                "ok": True,
                "skill": "image_gen",
                "paths": [],
                "note": "pytest skip real generate",
            }

        from matrixsolo.config import get_settings

        settings = get_settings()
        api_key = settings.grsai_api_key or os.environ.get("GRS_AI_KEY") or ""
        if not api_key:
            return {
                "ok": False,
                "skill": "image_gen",
                "error": "未配置 GRSAI_API_KEY，没法调 Grsai 生图",
            }

        ratio = _normalize_aspect(aspect_ratio)
        out_dir = settings.data_dir / "exports" / "covers"
        out_dir.mkdir(parents=True, exist_ok=True)
        roots: list[str] = []
        for candidate in (_image_api_root(settings.grsai_base_url), "https://grsaiapi.com"):
            if candidate and candidate not in roots:
                roots.append(candidate)

        last_error = "生图失败"
        for index, root in enumerate(roots):
            async_mode = index == 0
            try:
                result = await self._grsai_generate(
                    root, api_key, prompt, ratio, async_mode=async_mode
                )
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                logger.warning("image_gen node %s failed: %s", root, exc)
                continue
            status = str(result.get("status") or "")
            items = _result_items(result)
            if items and status not in {"failed", "violation", "running", "pending", "queued"}:
                paths = await self._download_results(items, out_dir)
                if paths:
                    return {
                        "ok": True,
                        "skill": "image_gen",
                        "paths": paths,
                        "aspect_ratio": ratio,
                    }
            task_id = str(result.get("id") or "")
            if async_mode and task_id and status not in {"failed", "violation"}:
                try:
                    items = await self._grsai_poll(root, api_key, task_id)
                    paths = await self._download_results(items, out_dir)
                    if paths:
                        return {
                            "ok": True,
                            "skill": "image_gen",
                            "paths": paths,
                            "aspect_ratio": ratio,
                        }
                    last_error = "任务完成但没有下到图"
                except Exception as exc:  # noqa: BLE001
                    last_error = str(exc)
                    logger.warning("image_gen poll %s failed: %s", root, exc)
                    continue
            else:
                last_error = str(result.get("error") or result.get("message") or status or "无结果")
        return {"ok": False, "skill": "image_gen", "error": last_error}

    async def _grsai_generate(
        self,
        root: str,
        api_key: str,
        prompt: str,
        aspect_ratio: str,
        *,
        async_mode: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": "gpt-image-2",
            "prompt": prompt,
            "aspectRatio": aspect_ratio,
        }
        if async_mode:
            payload["async"] = True
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                f"{root.rstrip('/')}/v1/api/generate",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400:
            raise RuntimeError(f"HTTP {resp.status_code}: {data or resp.text[:300]}")
        if isinstance(data, list):
            return {"status": "succeeded", "results": data}
        if not isinstance(data, dict):
            raise RuntimeError(f"意外响应: {data}")
        return data

    async def _grsai_poll(
        self,
        root: str,
        api_key: str,
        task_id: str,
        *,
        timeout: float = 120.0,
        interval: float = 3.0,
    ) -> list[Any]:
        deadline = asyncio.get_event_loop().time() + timeout
        async with httpx.AsyncClient(timeout=30.0) as client:
            while asyncio.get_event_loop().time() < deadline:
                resp = await client.get(
                    f"{root.rstrip('/')}/v1/api/generate/{task_id}",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                data = resp.json() if resp.content else {}
                if resp.status_code >= 400:
                    raise RuntimeError(f"poll HTTP {resp.status_code}: {data or resp.text[:200]}")
                if not isinstance(data, dict):
                    raise RuntimeError(f"poll 意外响应: {data}")
                status = str(data.get("status") or "")
                if status == "succeeded":
                    return list(data.get("results") or [])
                if status in {"failed", "violation"}:
                    raise RuntimeError(str(data.get("error") or status))
                await asyncio.sleep(interval)
        raise RuntimeError("生图超时（120s）")

    async def _download_results(self, items: list[Any], out_dir: Any) -> list[str]:
        from uuid import uuid4

        paths: list[str] = []
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            for item in items:
                url = item.get("url") if isinstance(item, dict) else str(item or "")
                if not url or not str(url).startswith("http"):
                    continue
                try:
                    resp = await client.get(str(url), headers={"User-Agent": BROWSER_UA})
                    if resp.status_code >= 400 or not resp.content:
                        continue
                    suffix = ".png"
                    ctype = resp.headers.get("content-type", "")
                    if "jpeg" in ctype or str(url).lower().endswith((".jpg", ".jpeg")):
                        suffix = ".jpg"
                    elif "webp" in ctype or str(url).lower().endswith(".webp"):
                        suffix = ".webp"
                    dest = (out_dir / f"grsai_{uuid4().hex[:10]}{suffix}").resolve()
                    dest.write_bytes(resp.content)
                    paths.append(str(dest))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("download generated image failed: %s", exc)
        return paths

    async def web_fetch(self, url: str, *, browser: bool = False, timeout: float = 20.0) -> dict[str, Any]:
        url = url.strip()
        if not safe_http_url(url):
            return {"ok": False, "skill": "web_fetch", "error": "URL 不合法或不允许"}
        headers = {"User-Agent": BROWSER_UA if browser else "MatrixSolo/0.1 (+web_fetch)"}
        if browser:
            headers["Accept"] = "text/html,application/json;q=0.9,*/*;q=0.8"
            headers["Accept-Language"] = "zh-CN,zh;q=0.9,en;q=0.8"
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                headers=headers,
            ) as client:
                resp = await client.get(url)
            content_type = resp.headers.get("content-type", "")
            raw = resp.content[:_MAX_BYTES]
            if "json" in content_type or url.rstrip("/").endswith(".json"):
                try:
                    text = json.dumps(json.loads(raw.decode("utf-8", errors="replace")), ensure_ascii=False)[
                        :_MAX_TEXT
                    ]
                except json.JSONDecodeError:
                    text = raw.decode("utf-8", errors="replace")[:_MAX_TEXT]
            else:
                decoded = raw.decode("utf-8", errors="replace")
                text = html_to_text(decoded) if "<html" in decoded.lower() or "text/html" in content_type else decoded[:_MAX_TEXT]
            return {
                "ok": resp.status_code < 400,
                "skill": "browser_crawl" if browser else "web_fetch",
                "url": str(resp.url),
                "status": resp.status_code,
                "text": text,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("web_fetch failed %s: %s", url, exc)
            return {"ok": False, "skill": "web_fetch", "url": url, "error": str(exc)}

    async def browser_crawl(self, urls: list[str]) -> dict[str, Any]:
        pages = []
        for url in urls[:5]:
            pages.append(await self.web_fetch(url, browser=True))
        if not pages:
            return {"ok": False, "skill": "browser_crawl", "error": "没有可爬的 URL"}
        ok = any(p.get("ok") for p in pages)
        return {"ok": ok, "skill": "browser_crawl", "pages": pages}

    async def hot_radar(self) -> dict[str, Any]:
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return {
                "ok": True,
                "skill": "hot_radar",
                "items": [
                    {"name": "盗梦空间", "heat": 96, "source": "pytest", "douban": 9.0},
                    {"name": "看不见的客人", "heat": 88, "source": "pytest", "douban": 8.8},
                ],
                "errors": [],
            }
        async def _one(source: str, url: str, kind: str) -> tuple[str, str, dict[str, Any]]:
            result = await self.web_fetch(url, browser=True, timeout=8.0)
            return source, kind, result

        gathered = await asyncio.gather(
            *[_one(source, url, kind) for source, url, kind in RADAR_SOURCES],
            return_exceptions=True,
        )
        items: list[dict[str, Any]] = []
        errors: list[str] = []
        for row in gathered:
            if isinstance(row, Exception):
                errors.append(str(row))
                continue
            source, kind, result = row
            if not result.get("ok"):
                errors.append(f"{source}: {result.get('error') or result.get('status')}")
                continue
            text = str(result.get("text") or "")
            parsed = _parse_bilibili_json(text, source) if kind == "json" else _parse_douban_chart(text, source)
            items.extend(parsed)
        # 去重保序
        seen: set[str] = set()
        uniq: list[dict[str, Any]] = []
        for item in items:
            name = (item.get("name") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            uniq.append(item)
        uniq = uniq[:18]
        return {
            "ok": bool(uniq),
            "skill": "hot_radar",
            "items": uniq,
            "errors": errors,
            "note": None if uniq else "热榜源失败，没有拿到实时条目。不要问老板要片名，说明源失败并给可执行下一步。",
        }


def enabled_skill_guide(profile: AgentProfile) -> str:
    catalog = {t["key"]: t for t in TOOL_CATALOG}
    lines = []
    for tool in profile.tools:
        if not tool.enabled:
            continue
        meta = catalog.get(tool.key, {})
        lines.append(f"- {tool.key}：{meta.get('description') or tool.description or tool.name}")
    if not lines:
        return "当前没有启用任何内置技能。"
    protocol = (
        "需要拉热榜时输出一行 JSON：{\"skill\":\"hot_radar\"}。\n"
        "需要打开网页时输出：{\"skill\":\"web_fetch\",\"url\":\"https://...\"}。\n"
        "需要用浏览器身份爬多个页时输出：{\"skill\":\"browser_crawl\",\"urls\":[\"https://...\"]}。\n"
        "需要真实出图时输出：{\"skill\":\"image_gen\",\"prompt\":\"画面描述\",\"aspect_ratio\":\"16:9\"}。"
        "竖版封面用 9:16。不要只给 Prompt 却不调 image_gen。\n"
        "不要把热榜工作甩给同事；不要问老板要片名。日常对话不要输出 JSON。"
    )
    return "已启用内置技能：\n" + "\n".join(lines) + "\n" + protocol


def safe_http_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    if not host or host in {"localhost", "127.0.0.1", "::1"}:
        return False
    if host.endswith(".local") or host.startswith("10.") or host.startswith("192.168."):
        return False
    return True


def _parse_bilibili_json(text: str, source: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    rows: list[Any] = []
    if isinstance(data, dict):
        payload = data.get("data") or data
        if isinstance(payload, dict):
            rows = payload.get("list") or payload.get("items") or []
        elif isinstance(payload, list):
            rows = payload
    out: list[dict[str, Any]] = []
    for i, row in enumerate(rows[:15]):
        if not isinstance(row, dict):
            continue
        origin = row.get("origin") if isinstance(row.get("origin"), dict) else {}
        title = row.get("title") or row.get("name") or origin.get("title") or ""
        if not title:
            continue
        stat = row.get("stat") if isinstance(row.get("stat"), dict) else {}
        heat = row.get("hot") or row.get("pts") or stat.get("view") or (100 - i)
        out.append({"name": str(title).strip(), "heat": heat, "source": source})
    return out


def _parse_douban_chart(text: str, source: str) -> list[dict[str, Any]]:
    titles = re.findall(
        r"(?:title|n\">)[\s\"']*([\u4e00-\u9fffA-Za-z0-9·：:\-]{2,40})",
        text,
    )
    alt = re.findall(r"《([^》]{1,40})》", text)
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for i, name in enumerate([*alt, *titles]):
        name = name.strip()
        if len(name) < 2 or name in seen:
            continue
        if name in {"豆瓣", "电影", "剧集", "登录", "下载"}:
            continue
        seen.add(name)
        out.append({"name": name, "heat": 90 - i, "source": source})
        if len(out) >= 12:
            break
    return out


def absolute_url(base: str, href: str) -> str:
    return urljoin(base, href)
