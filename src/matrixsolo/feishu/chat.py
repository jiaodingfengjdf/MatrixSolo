from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import multiprocessing as mp
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from matrixsolo.config import get_settings
from matrixsolo.feishu.client import FeishuClient
from matrixsolo.feishu.staff import (
    ROLE_TITLES,
    AgentRole,
    employee_title,
    employee_title_map,
    resolve_staff_apps,
)
from matrixsolo.gateway import TaskKind, get_gateway

logger = logging.getLogger(__name__)

TITLE_TO_ROLE = {title: role for role, title in ROLE_TITLES.items()}
_processed: set[str] = set()
_lock = threading.Lock()


def _ws_pid_path() -> Path:
    return get_settings().data_dir / "admin" / "feishu_ws.pids"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        SYNCHRONIZE = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _kill_pid(pid: int) -> None:
    if pid <= 0:
        return
    if os.name == "nt":
        import subprocess

        subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True,
            check=False,
        )
        return
    os.kill(pid, 15)


def _reap_stale_ws() -> None:
    path = _ws_pid_path()
    if not path.is_file():
        return
    try:
        raw_ids = [int(line.strip()) for line in path.read_text(encoding="utf-8").splitlines() if line.strip().isdigit()]
    except OSError:
        return
    mine = os.getpid()
    for pid in raw_ids:
        if pid == mine or not _pid_alive(pid):
            continue
        try:
            _kill_pid(pid)
        except OSError:
            logger.warning("Could not stop stale Feishu WS pid=%s", pid)
    try:
        path.unlink()
    except OSError:
        pass


def _write_ws_pids(pids: list[int]) -> None:
    path = _ws_pid_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(str(p) for p in pids if p), encoding="utf-8")


def _dedupe(event_id: str) -> bool:
    with _lock:
        if event_id in _processed:
            return False
        _processed.add(event_id)
        if len(_processed) > 2000:
            for item in list(_processed)[:500]:
                _processed.discard(item)
        return True


def resolve_role_from_event(payload: dict[str, Any]) -> str | None:
    header = payload.get("header") or {}
    app_id = header.get("app_id") or ""
    apps = resolve_staff_apps()
    for role, app in apps.items():
        if app.app_id and app.app_id == app_id:
            return role

    event = payload.get("event") or {}
    message = event.get("message") or {}
    title_map = employee_title_map()
    for m in message.get("mentions") or []:
        name = (m.get("name") or "").strip()
        if name in title_map:
            return title_map[name]
    text = extract_text(message)
    for title, role in title_map.items():
        if f"@{title}" in text:
            return role
    return None


URL_RE = re.compile(r"https?://[^\s<>\"']+")
INSTALL_WORDS = ("安装", "学会", "学习", "技能", "skill", "skill.md")
RADAR_ASK = re.compile(r"选题|热榜|做什么|干什么|拍什么|今天|档期|内容日历|不知道")
HUDDLE_ASK = re.compile(r"开工|工作流|跑[一上]?期|做一[期张]|先做|这期")
IMAGE_ASK = re.compile(
    r"生图|出图|画一[张幅个]|画张|画个|配图|生成图|出一[张幅]|出张|"
    r"做一[张幅]图|做张图|出个封面|出封面|封面图|生成封面|做封面|"
    r"海报|logo|标志|司徽|品牌|gpt-image|image-gen|帮我画|给我画|来一[张幅]|设计一[张幅]|设计专属"
)
MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def extract_text(message: dict[str, Any]) -> str:
    raw = message.get("content") or "{}"
    try:
        content = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return str(raw)
    if not isinstance(content, dict):
        return str(content)
    texts: list[str] = []
    if content.get("text"):
        texts.append(str(content["text"]))
    if content.get("file_name"):
        texts.append(str(content["file_name"]))
    if content.get("title"):
        texts.append(str(content["title"]))
    for key in ("content", "zh_cn", "en_us"):
        val = content.get(key)
        if isinstance(val, list):
            texts.append(_flatten_post(val))
        elif isinstance(val, dict):
            texts.append(_flatten_post(val.get("content") or []))
    text = " ".join(t for t in texts if t)
    text = re.sub(r"@_user_\d+", "", text)
    for title in employee_title_map().values():
        text = text.replace(f"@{title}", "")
    return text.strip()


def _flatten_post(blocks: Any) -> str:
    chunks: list[str] = []
    if not isinstance(blocks, list):
        return ""
    for block in blocks:
        if isinstance(block, list):
            chunks.append(_flatten_post(block))
            continue
        if not isinstance(block, dict):
            continue
        if block.get("text"):
            chunks.append(str(block["text"]))
        if block.get("href"):
            chunks.append(str(block["href"]))
        if block.get("url"):
            chunks.append(str(block["url"]))
    return " ".join(chunks)


def _mention_name_to_role(name: str) -> str | None:
    name = (name or "").strip()
    if not name:
        return None
    title_map = employee_title_map()
    if name in title_map:
        return title_map[name]
    for title, role in title_map.items():
        if title and title in name:
            return role
    return None


def extract_mentioned_roles(message: dict[str, Any]) -> set[str]:
    roles: set[str] = set()
    for item in message.get("mentions") or []:
        names: list[str] = []
        if isinstance(item, dict):
            names.extend(
                str(item.get(k) or "")
                for k in ("name", "key", "id")
            )
        else:
            names.append(str(getattr(item, "name", "") or ""))
        for name in names:
            role = _mention_name_to_role(name)
            if role:
                roles.add(role)
    raw = message.get("content") or ""
    blob = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
    for title, role in employee_title_map().items():
        if f"@{title}" in blob:
            roles.add(role)
    return roles


def huddle_leader(mentioned: set[str]) -> str:
    if "strategy" in mentioned:
        return "strategy"
    for role in (AgentRole.VISUAL, AgentRole.SCRIPT, AgentRole.EDITOR, AgentRole.OPS):
        if role.value in mentioned:
            return role.value
    return "strategy"


def should_huddle(mentioned: set[str], text: str) -> bool:
    """群里不 @ 或 @ 多人 / 开工，都走五岗工作流。单独 @ 一岗才一对一。"""
    if HUDDLE_ASK.search(text or ""):
        return True
    if len(mentioned) == 1:
        return False
    return True


def message_stamp(chat_id: str, message_id: str, text: str) -> str:
    """同一条用户消息的稳定去重键。飞书会给每个被 @ 的机器人各推一份，event_id 不同。"""
    if message_id:
        return f"msg:{message_id}"
    digest = hashlib.sha1(f"{chat_id}|{(text or '').strip()}".encode("utf-8")).hexdigest()[:16]
    return f"chat:{chat_id}:{digest}"


def huddle_claim_id(chat_id: str, message_id: str, text: str) -> str:
    """按群+原文认领，避免三岗各拿不同 event_id / message_id 各跑一遍。"""
    _ = message_id
    digest = hashlib.sha1(f"{chat_id}|{(text or '').strip()}".encode("utf-8")).hexdigest()[:20]
    chat_tail = re.sub(r"[^a-zA-Z0-9_-]", "", (chat_id or "chat")[-16:])
    return f"{chat_tail}-{digest}"


def try_claim_huddle(claim_id: str, role: str) -> bool:
    """只让一个岗跑 huddle，避免三岗同时闲聊。"""
    token = re.sub(r"[^a-zA-Z0-9._-]", "-", (claim_id or "").strip()) or f"anon-{time.time_ns()}"
    root = get_settings().data_dir / "admin" / "huddle_claims"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{token}.claim"
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(role)
        return True
    except FileExistsError:
        return False


def extract_card_value(payload: dict[str, Any]) -> dict[str, Any]:
    event = payload.get("event") or {}
    action = event.get("action") or payload.get("action") or {}
    if not isinstance(action, dict):
        action = {}
    value = action.get("value") or payload.get("value") or {}
    if not isinstance(value, dict):
        return {}
    return {str(k): v for k, v in value.items() if v is not None}


def card_action_to_payload(data: Any, app_id: str) -> dict[str, Any]:
    event = _obj_get(data, "event")
    action = _obj_get(event, "action") or {}
    raw = _obj_get(action, "value") if not isinstance(action, dict) else action.get("value")
    value = raw if isinstance(raw, dict) else {}
    return {
        "kind": "card_action",
        "header": {
            "event_type": "card.action.trigger",
            "app_id": app_id,
        },
        "value": {str(k): v for k, v in value.items() if v is not None},
    }


def _card_extra(value: dict[str, Any]) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    for key, raw in value.items():
        if key in {"workflow_id", "stage", "action"}:
            continue
        if key in {"index", "title_index"}:
            try:
                extra[key] = int(raw)
            except (TypeError, ValueError):
                extra[key] = 0
        else:
            extra[key] = raw
    return extra


async def handle_card_action(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("value") or extract_card_value(payload)
    workflow_id = str(value.get("workflow_id") or "")
    stage = str(value.get("stage") or "")
    action = str(value.get("action") or "")
    _trace_feishu("card", workflow_id=workflow_id, stage=stage, action=action)
    if not (workflow_id and stage and action):
        logger.warning("Feishu card missing value: %s", value)
        return {"ok": False, "msg": "empty-card"}
    from matrixsolo.orchestration import ProductionOrchestrator

    orch = ProductionOrchestrator()
    try:
        state = await orch.resume_hitl(workflow_id, stage, action, _card_extra(value))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Feishu card resume failed %s", workflow_id)
        chat_id = get_settings().feishu_hitl_chat_id
        if chat_id:
            try:
                await FeishuClient().send_text(
                    chat_id,
                    f"卡片处理失败：{exc}",
                    role="strategy",
                )
            except Exception:  # noqa: BLE001
                logger.exception("Feishu card error notice failed")
        return {"ok": False, "msg": str(exc)}
    logger.info("Feishu card resumed %s → %s", workflow_id, state.status.value)
    return {"ok": True, "status": state.status.value}


def extract_urls(text: str) -> list[str]:
    return [u.rstrip(".,)，。") for u in URL_RE.findall(text or "")]


def is_install_intent(text: str, filename: str = "") -> bool:
    lower = (filename or "").lower()
    if lower.endswith((".md", ".markdown", ".zip")):
        return True
    urls = extract_urls(text)
    if not urls and not filename:
        return False
    blob = f"{text} {filename}".lower()
    if any(word in blob for word in INSTALL_WORDS):
        return True
    return any(u.lower().split("?")[0].endswith((".md", ".markdown", ".zip")) for u in urls)


def _file_meta(message: dict[str, Any]) -> tuple[str, str]:
    raw = message.get("content") or "{}"
    try:
        content = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return "", ""
    if not isinstance(content, dict):
        return "", ""
    return str(content.get("file_key") or ""), str(content.get("file_name") or "")


async def handle_im_message(payload: dict[str, Any]) -> dict[str, Any]:
    header = payload.get("header") or {}
    event_id = header.get("event_id") or ""
    if event_id and not _dedupe(event_id):
        return {"code": 0, "msg": "duplicate"}

    event = payload.get("event") or {}
    sender = event.get("sender") or {}
    if (sender.get("sender_type") or "").lower() == "app":
        return {"code": 0, "msg": "ignore bot"}

    message = event.get("message") or {}
    msg_type = (message.get("message_type") or "text").lower()
    if msg_type not in {"text", "file", "post", "media"}:
        return {"code": 0, "msg": "ignore type"}

    role = resolve_role_from_event(payload)
    if not role:
        logger.info("Feishu message: cannot resolve role, skip")
        return {"code": 0, "msg": "no role"}

    text = extract_text(message)
    chat_id = message.get("chat_id") or ""
    message_id = message.get("message_id") or ""
    file_key, file_name = _file_meta(message)
    if not chat_id:
        return {"code": 0, "msg": "empty"}

    if is_install_intent(text, file_name):
        reply = await _install_skill_from_message(role, text, message_id, file_key, file_name)
        await _deliver(role, chat_id, message_id, reply)
        return {"code": 0, "msg": "installed", "role": role}

    if not text:
        return {"code": 0, "msg": "empty"}

    stamp = message_stamp(chat_id, message_id, text)
    if not _dedupe(stamp):
        _trace_feishu("skip-dup", role=role, stamp=stamp, text=text[:80])
        return {"code": 0, "msg": "duplicate-message", "role": role}

    mentioned = extract_mentioned_roles(message)
    huddle = should_huddle(mentioned, text)
    _trace_feishu(
        "in",
        role=role,
        mentioned=[str(r) for r in mentioned],
        huddle=huddle,
        text=text[:120],
        message_id=message_id,
        stamp=stamp,
    )
    if huddle:
        claim = huddle_claim_id(chat_id, message_id, text)
        if not try_claim_huddle(claim, str(role)):
            _trace_feishu("skip-claimed", role=str(role), claim=claim, text=text[:80])
            return {"code": 0, "msg": "huddle-claimed", "role": role}
        logger.info(
            "Feishu huddle by %s roles=%s text=%s",
            role,
            [r.value for r in mentioned],
            text[:80],
        )
        from matrixsolo.orchestration.huddle import run_studio_huddle

        await run_studio_huddle(
            user_text=text,
            chat_id=chat_id,
            message_id=message_id,
            mentioned=mentioned or {role},
        )
        return {"code": 0, "msg": "huddle", "role": role}

    logger.info("Feishu chat role=%s text=%s", role, text[:80])
    reply, images = await _generate_reply(role, text)
    await _deliver(role, chat_id, message_id, reply, images)
    return {"code": 0, "msg": "replied", "role": role}


def _resolve_image_file(raw: str) -> str | None:
    text = (raw or "").strip().strip('"').strip("'").replace("\\", "/")
    if not text or text.startswith("http"):
        return None
    settings = get_settings()
    name = Path(text).name
    roots = [
        Path(text),
        Path.cwd() / text,
        settings.data_dir / text,
        settings.data_dir / "exports" / "covers" / name,
        Path(__file__).resolve().parents[3] / text,
        Path(__file__).resolve().parents[3] / "data" / "exports" / "covers" / name,
    ]
    seen: set[str] = set()
    for candidate in roots:
        try:
            path = candidate if candidate.is_absolute() else (Path.cwd() / candidate)
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            if path.is_file() and path.stat().st_size > 0:
                return str(path.resolve())
        except OSError:
            continue
    return None


def _extract_local_images(text: str) -> tuple[str, list[str]]:
    found: list[str] = []
    for match in MD_IMAGE_RE.finditer(text or ""):
        resolved = _resolve_image_file(match.group(1))
        if resolved and resolved not in found:
            found.append(resolved)
    cleaned = MD_IMAGE_RE.sub("", text or "")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, found


def _merge_image_paths(*groups: list[str] | None) -> list[str]:
    out: list[str] = []
    for group in groups:
        for raw in group or []:
            resolved = _resolve_image_file(str(raw))
            if resolved and resolved not in out:
                out.append(resolved)
    return out


async def _deliver(
    role: str,
    chat_id: str,
    message_id: str,
    reply: str,
    images: list[str] | None = None,
) -> None:
    client = FeishuClient()
    text, embedded = _extract_local_images(reply or "")
    files = _merge_image_paths(images, embedded)
    logger.info("Feishu deliver role=%s images=%s chat=%s", role, len(files), bool(chat_id))
    if text:
        if message_id:
            ok = await client.reply_text(message_id, text, role=role)
            if not ok:
                await client.send_text(chat_id, text, role=role)
        else:
            await client.send_text(chat_id, text, role=role)
    failed: list[str] = []
    for path in files:
        sent = bool(chat_id and await client.send_image(chat_id, path, role=role))
        if not sent and message_id:
            sent = await client.reply_image(message_id, path, role=role)
        if not sent:
            failed.append(path)
            logger.error("Feishu image deliver failed [%s]: %s", role, path)
    if failed:
        note = "图已生成，但飞书没发出去。给视觉机器人开通「获取与上传图片或文件资源」权限后再试。"
        if chat_id:
            await client.send_text(chat_id, note, role=role)
        elif message_id:
            await client.reply_text(message_id, note, role=role)


async def _install_skill_from_message(
    role: str,
    text: str,
    message_id: str,
    file_key: str,
    file_name: str,
) -> str:
    from matrixsolo.admin.store import get_profile_store
    from matrixsolo.skills.package import (
        SkillInstallError,
        install_skill_package,
        package_from_url,
        parse_skill_bytes,
    )

    try:
        pack = None
        raw = b""
        filename = file_name
        origin = ""
        urls = extract_urls(text)
        if file_key and message_id:
            client = FeishuClient()
            data = await client.download_message_file(message_id, file_key, role=role)
            if not data:
                return f"文件没下下来。把 SKILL.md 或 zip 再发一次，或者贴一个可访问的地址。"
            raw = data
            pack = parse_skill_bytes(data, file_name or "skill.md")
            pack.source = "feishu"
            pack.origin = file_name or message_id
            origin = pack.origin
        elif urls:
            origin = urls[0]
            pack = await package_from_url(origin)
            pack.source = "feishu"
            filename = origin.rsplit("/", 1)[-1]
        else:
            return "把 SKILL.md、zip，或技能地址发我，我才能装。"

        skill = install_skill_package(role, pack, raw=raw, filename=filename)
        get_profile_store().install_skill(role, skill)
        return f"已学会《{skill.name}》。下次相关任务我会直接用，不用再教一遍。"
    except SkillInstallError as exc:
        return f"这个技能我没装上：{exc}"
    except Exception as exc:  # noqa: BLE001
        logger.exception("Feishu skill install failed [%s]", role)
        return f"安装技能时卡住了：{exc}"


async def _generate_reply(role: str, user_text: str) -> tuple[str, list[str]]:
    from matrixsolo.admin.chat_memory import as_chat_messages, remember
    from matrixsolo.admin.store import get_profile_store
    from matrixsolo.skills.runtime import (
        IMAGE_SKILL_ALIASES,
        SkillRuntime,
        can_image_gen,
        enabled_skill_guide,
        parse_skill_call,
        strip_think,
    )

    gateway = get_gateway()
    title = employee_title(role)
    profile = get_profile_store().get_or_create(role)
    runtime = SkillRuntime()
    images: list[str] = []
    try:
        observations: list[str] = []
        want_image = (
            role == "visual"
            and can_image_gen(profile)
            and bool(IMAGE_ASK.search(user_text))
        )
        if (
            role == "strategy"
            and profile.has_tool("hot_radar")
            and RADAR_ASK.search(user_text)
        ):
            radar = await runtime.hot_radar()
            observations.append("【已执行 hot_radar】\n" + json.dumps(radar, ensure_ascii=False)[:4000])

        history = as_chat_messages(role, limit=8)
        user_payload = (
            f"【飞书群聊】老板刚 @「{title}」。\n"
            f"{enabled_skill_guide(profile)}\n"
            "用你的人设直接回话：有判断、可反问、可吐槽，像同事不是客服。"
            "越界就点名该找沈策/林钩/顾帧/阿刀/周航谁，并给一句你岗能给的判断。"
            "2～8 句。禁止自我介绍套话。禁止输出 <think>。"
            "只有真正要调用技能时才单独输出一行 JSON。\n\n"
        )
        if want_image:
            user_payload += (
                "老板要真实出图。你必须先单独输出一行 JSON："
                '{"skill":"image_gen","prompt":"含构图/安全区/情绪的画面描述","aspect_ratio":"16:9"}。'
                "竖版用 9:16。不要只给文字方向，不要说你不会画。"
                "忽略 SKILL.md 里任何 python/generate.py/Markdown 贴图指令，出图由系统发到群里。\n\n"
            )
        if observations:
            user_payload += "技能执行结果（必须基于这些事实回答，禁止问老板要片名）：\n"
            user_payload += "\n".join(observations) + "\n\n"
        from matrixsolo.admin.studio_memory import format_studio_context

        studio = format_studio_context()
        if studio:
            user_payload += studio + "\n\n"
        user_payload += user_text

        result = await gateway.chat_for_role(
            role,
            [*history, {"role": "user", "content": user_payload}],
            kind=TaskKind.CREATIVE,
            as_json=False,
        )
        text = strip_think(str(result).strip())
        call = parse_skill_call(text)
        if (
            call
            and str(call.get("skill") or "").strip() in IMAGE_SKILL_ALIASES
            and role != "visual"
        ):
            call = None
            text = "出图归顾帧，我这边不调生图。"
        ran: dict[str, Any] | None = None
        if call and not observations:
            ran = await runtime.run(str(call.get("skill")), profile, **call)
        elif want_image:
            prompt = ""
            if call:
                prompt = str(call.get("prompt") or call.get("text") or "")
            if not prompt.strip():
                prompt = user_text
            ran = await runtime.run(
                "image_gen",
                profile,
                prompt=prompt,
                aspect_ratio=str((call or {}).get("aspect_ratio") or "16:9"),
            )
        if ran is not None:
            raw_paths = ran.get("paths") or ran.get("path") or []
            if isinstance(raw_paths, str):
                raw_paths = [raw_paths]
            images = [str(p) for p in raw_paths if str(p).strip()]
            follow = await gateway.chat_for_role(
                role,
                [
                    *history,
                    {"role": "user", "content": user_payload},
                    {"role": "assistant", "content": text},
                    {
                        "role": "user",
                        "content": (
                            "技能结果如下。改用人话回复老板，禁止再输出 JSON、<think>、Markdown 图片和任何文件路径。"
                            "如果已出图，一两句说构图/情绪即可，图会由系统单独发到群里。\n"
                            + json.dumps(
                                {
                                    "ok": bool(ran.get("ok")),
                                    "error": ran.get("error"),
                                    "image_count": len(images),
                                    "aspect_ratio": ran.get("aspect_ratio"),
                                },
                                ensure_ascii=False,
                            )
                        ),
                    },
                ],
                kind=TaskKind.CREATIVE,
                as_json=False,
            )
            text = strip_think(str(follow).strip())
            if ran.get("ok") and images:
                text, _ = _extract_local_images(text)
                if not text:
                    text = "图发群里了。顶部安全区留好了，标题不会抢脸。"
            elif not ran.get("ok"):
                err = str(ran.get("error") or "生图失败")
                text = f"这张没出成：{err}"
        elif call:
            text = strip_think(re.sub(r"```json.*?```", "", text, flags=re.DOTALL).strip())
            text = strip_think(re.sub(r"\{[^{}]*\"skill\"[^{}]*\}", "", text).strip())

        if not text:
            text = f"嗯，我是{title}，这条我先记下。"
        remember(role, user_text, text)
        return text, images
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM reply failed for %s", role)
        return f"我是{title}。刚才卡了一下：{exc}", images


def _obj_get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _plain(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, (str, int, float, bool)):
        return str(val)
    for key in ("open_id", "user_id", "union_id", "name", "key"):
        got = _obj_get(val, key)
        if got:
            return str(got)
    return str(val)


def event_to_payload(data: Any, app_id: str) -> dict[str, Any]:
    """把 lark SDK 事件收成可跨进程 pickle 的纯 dict。"""
    header = _obj_get(data, "header")
    event = _obj_get(data, "event", data)
    message = _obj_get(event, "message") or {}
    sender = _obj_get(event, "sender") or {}
    raw_mentions = _obj_get(message, "mentions") or []
    mentions = []
    for item in raw_mentions:
        mentions.append(
            {
                "name": _plain(_obj_get(item, "name")),
                "key": _plain(_obj_get(item, "key")),
            }
        )
    content = _obj_get(message, "content") or "{}"
    if not isinstance(content, str):
        try:
            content = json.dumps(content, ensure_ascii=False, default=str)
        except TypeError:
            content = str(content)
    return {
        "header": {
            "event_id": _plain(_obj_get(header, "event_id")),
            "event_type": "im.message.receive_v1",
            "app_id": app_id,
        },
        "event": {
            "sender": {
                "sender_type": _plain(_obj_get(sender, "sender_type")) or "user",
                "sender_id": _plain(_obj_get(sender, "sender_id")),
            },
            "message": {
                "chat_id": _plain(_obj_get(message, "chat_id")),
                "message_id": _plain(_obj_get(message, "message_id")),
                "message_type": _plain(_obj_get(message, "message_type")) or "text",
                "content": content,
                "mentions": mentions,
            },
        },
    }


def _trace_feishu(stage: str, **fields: Any) -> None:
    try:
        path = get_settings().data_dir / "logs" / "feishu_in.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {"ts": time.time(), "stage": stage, **fields}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    except Exception:  # noqa: BLE001
        logger.exception("feishu trace failed")


def run_feishu_ws_bot(
    role_value: str,
    app_id: str,
    app_secret: str,
    queue: Any | None = None,
    parent_pid: int = 0,
) -> None:
    """独立进程入口：每个飞书应用独占一个 asyncio loop（绕开 lark SDK 全局 loop 限制）。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    log = logging.getLogger(f"matrixsolo.feishu.ws.{role_value}")
    if parent_pid:
        def _die_if_parent_gone() -> None:
            while True:
                time.sleep(2)
                if not _pid_alive(parent_pid):
                    os._exit(0)

        threading.Thread(target=_die_if_parent_gone, name="parent-watch", daemon=True).start()

    # 必须在 import lark_oapi.ws 之前绑定本进程 loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    import lark_oapi as lark
    import lark_oapi.ws.client as ws_client
    from lark_oapi.event.dispatcher_handler import EventDispatcherHandler

    ws_client.loop = loop

    def on_message(data: Any) -> None:
        try:
            payload = event_to_payload(data, app_id)
            message = ((payload.get("event") or {}).get("message") or {})
            _trace_feishu(
                "enqueue",
                role=role_value,
                app_id=app_id,
                message_id=message.get("message_id") or "",
                chat_id=message.get("chat_id") or "",
                queued=queue is not None,
            )
            if queue is None:
                log.error("Feishu WS [%s] missing parent queue; drop to avoid parallel chat", role_value)
                return
            queue.put(payload)
        except Exception:  # noqa: BLE001
            log.exception("Feishu WS handler error")

    def on_card(data: Any):
        from lark_oapi.event.callback.model.p2_card_action_trigger import (
            P2CardActionTriggerResponse,
        )

        try:
            payload = card_action_to_payload(data, app_id)
            _trace_feishu(
                "card-enqueue",
                role=role_value,
                app_id=app_id,
                value=payload.get("value") or {},
                queued=queue is not None,
            )
            if queue is not None:
                queue.put(payload)
        except Exception:  # noqa: BLE001
            log.exception("Feishu card handler error")
        return P2CardActionTriggerResponse(
            {
                "toast": {
                    "type": "info",
                    "content": "收到，工作室接着干。",
                }
            }
        )

    try:
        handler = (
            EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(on_message)
            .register_p2_card_action_trigger(on_card)
            .build()
        )
        cli = lark.ws.Client(
            app_id,
            app_secret,
            event_handler=handler,
            log_level=lark.LogLevel.INFO,
        )
        title = employee_title(role_value)
        log.info("Feishu WS connecting [%s] app_id=%s", title, app_id)
        cli.start()
    except Exception:  # noqa: BLE001
        log.exception("Feishu WS process crashed [%s]", role_value)
    finally:
        try:
            if not loop.is_closed():
                loop.close()
        except Exception:  # noqa: BLE001
            pass


class FeishuChatWorker:
    """五岗飞书长连接：子进程只收事件，主进程统一跑工作流。"""

    def __init__(self) -> None:
        self._procs: list[mp.Process] = []
        self._stop = threading.Event()
        self._queue: Any | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self) -> None:
        settings = get_settings()
        if not settings.enable_feishu_chat:
            logger.info("Feishu chat worker disabled")
            return

        _reap_stale_ws()
        ctx = mp.get_context("spawn")
        self._queue = ctx.Queue()
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = asyncio.get_event_loop()
        threading.Thread(target=self._consume, name="feishu-huddle-bus", daemon=True).start()

        threading.Thread(target=self._boot, name="feishu-ws-boot", daemon=True).start()

    def _boot(self) -> None:
        """按当前员工注册表拉起所有启用且已配置凭证的 Feishu WS 子进程."""
        ctx = mp.get_context("spawn")
        parent_pid = os.getpid()
        apps = resolve_staff_apps()
        for role, app in apps.items():
            if self._stop.is_set():
                break
            if not (app.app_id and app.app_secret):
                continue
            proc = ctx.Process(
                target=run_feishu_ws_bot,
                args=(role, app.app_id, app.app_secret, self._queue, parent_pid),
                name=f"feishu-ws-{role}",
                daemon=True,
            )
            proc.start()
            self._procs.append(proc)
            logger.info(
                "Feishu WS process started for %s pid=%s (%s)",
                employee_title(role),
                proc.pid,
                app.app_id,
            )
            time.sleep(0.8)
        _write_ws_pids([p.pid for p in self._procs if p.pid])

    def reload_apps(self) -> dict[str, Any]:
        """热重载：停掉旧 WS 子进程并按注册表重新拉起（新员工上岗/停用即时生效）."""
        started = bool(self._loop and self._queue)
        if not started:
            self.start()
            return {"ok": True, "reloaded": True, "note": "worker was not running; started"}
        for proc in self._procs:
            if proc.is_alive():
                proc.terminate()
        for proc in self._procs:
            proc.join(timeout=3)
            if proc.is_alive():
                proc.kill()
        self._procs.clear()
        if self._stop.is_set():
            self._stop.clear()
        threading.Thread(target=self._boot, name="feishu-ws-reload", daemon=True).start()
        return {"ok": True, "reloaded": True}

    def _consume(self) -> None:
        import queue as queue_mod

        while not self._stop.is_set():
            try:
                payload = self._queue.get(timeout=0.3) if self._queue is not None else None
            except queue_mod.Empty:
                continue
            if not payload or self._loop is None:
                continue
            asyncio.run_coroutine_threadsafe(self._handle(payload), self._loop)

    async def _handle(self, payload: dict[str, Any]) -> None:
        try:
            if payload.get("kind") == "card_action":
                logger.info(
                    "Feishu card bus value=%s",
                    payload.get("value") or {},
                )
                await handle_card_action(payload)
                return
            header = payload.get("header") or {}
            message = ((payload.get("event") or {}).get("message") or {})
            logger.info(
                "Feishu bus got app=%s msg=%s",
                header.get("app_id") or "",
                message.get("message_id") or "",
            )
            await handle_im_message(payload)
        except Exception:  # noqa: BLE001
            logger.exception("Feishu huddle bus failed")

    def shutdown(self) -> None:
        self._stop.set()
        for proc in self._procs:
            if proc.is_alive():
                proc.terminate()
        for proc in self._procs:
            proc.join(timeout=3)
            if proc.is_alive():
                proc.kill()
        self._procs.clear()
        try:
            _ws_pid_path().unlink(missing_ok=True)
        except OSError:
            pass


_worker: FeishuChatWorker | None = None


def get_chat_worker() -> FeishuChatWorker:
    global _worker
    if _worker is None:
        _worker = FeishuChatWorker()
    return _worker
