from __future__ import annotations

import io
import logging
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from uuid import uuid4

import httpx

from matrixsolo.admin.models import PromptSkill
from matrixsolo.config import get_settings
from matrixsolo.skills.runtime import BROWSER_UA, html_to_text, safe_http_url

logger = logging.getLogger(__name__)

SkillSource = Literal["manual", "upload", "url", "feishu"]

_MAX_PACK = 2_000_000
_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)


class SkillInstallError(ValueError):
    pass


@dataclass
class SkillPackage:
    name: str
    description: str
    content: str
    origin: str = ""
    source: SkillSource = "upload"
    skill_type: Literal["prompt", "runtime", "mcp", "http"] = "prompt"
    allowed_tools: list[str] | None = None
    mcp_server: str = ""


def parse_skill_md(raw: str, *, fallback_name: str = "untitled-skill") -> SkillPackage:
    text = raw.replace("\ufeff", "").strip()
    if not text:
        raise SkillInstallError("空的技能文件")
    name = fallback_name
    description = ""
    skill_type: Literal["prompt", "runtime", "mcp", "http"] = "prompt"
    allowed_tools: list[str] = []
    mcp_server = ""
    body = text
    match = _FRONTMATTER.match(text)
    if match:
        meta_raw, body = match.group(1), match.group(2).strip()
        meta = _parse_simple_yaml(meta_raw)
        name = str(meta.get("name") or name).strip() or fallback_name
        description = str(meta.get("description") or "").strip()
        raw_type = str(meta.get("type") or "prompt").strip().lower()
        if raw_type in {"prompt", "runtime", "mcp", "http"}:
            skill_type = raw_type  # type: ignore[assignment]
        allowed_tools = [
            t.strip() for t in str(meta.get("allowed_tools") or "").replace(",", " ").split() if t.strip()
        ]
        mcp_server = str(meta.get("mcp_server") or "").strip()
    if not body:
        raise SkillInstallError("SKILL.md 没有正文")
    if not description:
        description = body.splitlines()[0][:180]
    content = body if not description else f"{description}\n\n{body}"
    return SkillPackage(
        name=name[:64],
        description=description[:1024],
        content=content[:20000],
        skill_type=skill_type,
        allowed_tools=allowed_tools,
        mcp_server=mcp_server,
    )


def parse_skill_bytes(data: bytes, filename: str = "") -> SkillPackage:
    if len(data) > _MAX_PACK:
        raise SkillInstallError("技能包超过 2MB")
    lower = filename.lower()
    if lower.endswith(".zip") or data[:2] == b"PK":
        return _from_zip(data, filename)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SkillInstallError("文件不是 UTF-8 文本或 zip") from exc
    fallback = Path(filename).stem if filename else "imported-skill"
    return parse_skill_md(text, fallback_name=_slug(fallback))


async def fetch_skill_url(url: str) -> tuple[bytes, str]:
    if not safe_http_url(url):
        raise SkillInstallError("技能地址不合法")
    async with httpx.AsyncClient(
        timeout=25.0,
        follow_redirects=True,
        headers={"User-Agent": BROWSER_UA, "Accept": "*/*"},
    ) as client:
        resp = await client.get(url)
    if resp.status_code >= 400:
        raise SkillInstallError(f"下载失败 HTTP {resp.status_code}")
    data = resp.content[:_MAX_PACK + 1]
    if len(data) > _MAX_PACK:
        raise SkillInstallError("技能包超过 2MB")
    name = Path(urlparse(str(resp.url)).path).name or "skill.md"
    ctype = resp.headers.get("content-type", "")
    if "zip" in ctype and not name.lower().endswith(".zip"):
        name = "skill.zip"
    return data, name


async def package_from_url(url: str) -> SkillPackage:
    data, filename = await fetch_skill_url(url)
    lower = filename.lower()
    if lower.endswith((".md", ".markdown", ".txt", ".zip")) or data[:2] == b"PK":
        pack = parse_skill_bytes(data, filename)
    else:
        text = data.decode("utf-8", errors="replace")
        extracted = html_to_text(text) if "<html" in text.lower() else text
        if len(extracted.strip()) < 40:
            raise SkillInstallError("网页内容太少，不像技能说明书")
        pack = SkillPackage(
            name=_slug(Path(filename).stem or "web-skill"),
            description=extracted.splitlines()[0][:180],
            content=extracted[:20000],
        )
    pack.origin = url
    pack.source = "url"
    return pack


def persist_pack_files(role: str, skill_id: str, raw: bytes, filename: str, pack: SkillPackage) -> Path:
    root = get_settings().data_dir / "admin" / "skill_packs" / role / skill_id
    root.mkdir(parents=True, exist_ok=True)
    desc = pack.description.replace("\n", " ").replace(":", "：")
    (root / "SKILL.md").write_text(
        f"---\nname: {pack.name}\ndescription: {desc}\ntype: {pack.skill_type}\n"
        f"allowed_tools: {' '.join(pack.allowed_tools or [])}\nmcp_server: {pack.mcp_server}\n"
        f"---\n\n{pack.content}\n",
        encoding="utf-8",
    )
    if filename:
        safe = Path(filename).name
        (root / "origin_name.txt").write_text(safe, encoding="utf-8")
    if raw[:2] == b"PK":
        (root / "source.zip").write_bytes(raw[:_MAX_PACK])
    return root


def to_prompt_skill(pack: SkillPackage) -> PromptSkill:
    return PromptSkill(
        id=str(uuid4()),
        name=pack.name,
        content=pack.content,
        enabled=True,
        skill_type=pack.skill_type,
        allowed_tools=pack.allowed_tools or [],
        mcp_server=pack.mcp_server,
        source=pack.source,
        origin=pack.origin,
        description=pack.description,
    )


def install_skill_package(role: str, pack: SkillPackage, raw: bytes = b"", filename: str = "") -> PromptSkill:
    skill = to_prompt_skill(pack)
    persist_pack_files(role, skill.id, raw, filename, pack)
    return skill


def _from_zip(data: bytes, filename: str) -> SkillPackage:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise SkillInstallError("不是有效的 zip") from exc
    md_name = None
    for info in zf.infolist():
        if info.is_dir():
            continue
        path = info.filename.replace("\\", "/")
        if path.split("/")[-1].lower() == "skill.md":
            md_name = info.filename
            break
    if not md_name:
        raise SkillInstallError("zip 里找不到 SKILL.md")
    raw = zf.read(md_name)
    fallback = Path(filename).stem if filename else Path(md_name).parent.name or "zip-skill"
    return parse_skill_md(raw.decode("utf-8", errors="replace"), fallback_name=_slug(fallback))


def _parse_simple_yaml(block: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line or line.strip().startswith("#"):
            continue
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip().strip("'").strip('"')
    return out


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\-]+", "-", name.strip().lower()).strip("-")
    return (slug or "imported-skill")[:64]
