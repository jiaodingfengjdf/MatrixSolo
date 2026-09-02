from __future__ import annotations

import logging
import re
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from matrixsolo.admin.studio_memory import (
    append_calendar_rows,
    format_studio_context,
    save_studio_context,
)
from matrixsolo.feishu.client import FeishuClient
from matrixsolo.feishu.staff import AgentRole
from matrixsolo.gateway import TaskKind, get_gateway
from matrixsolo.models import CoverVariant, TopicCandidate, WorkflowState, WorkflowStatus
from matrixsolo.orchestration.store import WorkflowStore
from matrixsolo.skills.runtime import SkillRuntime, can_image_gen, strip_think

logger = logging.getLogger(__name__)

PRODUCE_ASK = re.compile(
    r"logo|标志|司徽|品牌|海报|封面|宣发|出图|生图|设计|做一[期张]|跑[一上]?期",
    re.I,
)


def huddle_job(text: str) -> str:
    blob = text or ""
    if re.search(r"logo|标志|司徽|品牌", blob, re.I):
        return "logo"
    if PRODUCE_ASK.search(blob):
        return "poster"
    return "talk"


def _ctx_block() -> str:
    ctx = format_studio_context()
    return f"{ctx}\n\n" if ctx else ""


class HuddleState(TypedDict, total=False):
    workflow: dict[str, Any]
    user_text: str
    chat_id: str
    message_id: str
    need_visual: bool
    need_script: bool
    need_editor: bool
    need_ops: bool
    job: str
    film_name: str
    angle: str
    mood: str
    brief: str
    hook: str
    poster_prompt: str
    aspect_ratio: str
    image_paths: list[str]


def _wf(state: HuddleState) -> WorkflowState:
    return WorkflowState.model_validate(state["workflow"])


def _dump(wf: WorkflowState) -> dict[str, Any]:
    return wf.model_dump(mode="json")


class StudioHuddle:
    """飞书群开工 huddle：总编定切口 → 视觉出图 → 剪辑看画幅。"""

    def __init__(self) -> None:
        self.store = WorkflowStore()
        self.feishu = FeishuClient()
        self.runtime = SkillRuntime()
        self._graph = self._build()

    def _build(self):
        g = StateGraph(HuddleState)

        async def brief_node(state: HuddleState) -> HuddleState:
            wf = _wf(state)
            wf.status = WorkflowStatus.STRATEGY
            wf.log("Huddle → strategy")
            job = str(state.get("job") or huddle_job(state.get("user_text") or "")).strip().lower()
            user_text = state.get("user_text") or ""
            if job == "talk":
                reply = await _text_role(
                    "strategy",
                    (
                        f"{_ctx_block()}"
                        "你是总编沈策。老板在群里说话，没点名也要你先接。这是五岗流水线第一棒。\n"
                        "用 2～4 句接住老板的话，点一下后面视觉/文案/剪辑/运营会按序接。\n"
                        "不要布置新的出图任务，不要问老板选哪条。禁止 <think>。\n\n"
                        f"{user_text}"
                    ),
                )
                text = reply or "收到。五岗按序过一遍。"
                await self._say(AgentRole.STRATEGY, state, text, reply=True)
                wf.log(f"日常 huddle / {job}")
                self.store.save(wf)
                return {**state, "workflow": _dump(wf), "job": job}

            data = await _json_role(
                "strategy",
                (
                    "老板在飞书群里说话，没点名也要你拍板。你是总编沈策，立刻定切口，不要再问老板选哪条。"
                    "这是流水线第一棒，后面视觉/文案/剪辑/运营会按你的切口接着干。\n"
                    "若是 logo/品牌：公司名默认 MatrixSolo，影视自媒体工作室，气质稳、科技、可缩成头像。\n"
                    "只输出 JSON："
                    '{"job":"logo|poster","film_name":"主题或公司名","angle":"方向词","mood":"情绪词",'
                    '"hook":"一句钩子","brief":"给视觉的两句方向"}\n\n'
                    f"{user_text}"
                ),
            )
            film = str(data.get("film_name") or "MatrixSolo").strip()
            angle = str(data.get("angle") or "稳重科技").strip()
            mood = str(data.get("mood") or "冷蓝克制").strip()
            hook = str(data.get("hook") or "").strip()
            brief = str(data.get("brief") or "").strip()
            if "logo" in user_text.lower() or "标志" in user_text or "品牌" in user_text:
                job = "logo"
            wf.selected_topic = TopicCandidate(
                film_name=film,
                reason=brief or f"{angle} / {mood}",
                hook_points=[hook] if hook else [],
                source="feishu_huddle",
            )
            wf.topic_custom_note = user_text
            next_step = "视觉出 logo" if job == "logo" else "视觉出图"
            text = (
                f"开工。按工作流走，不并行闲聊。\n"
                f"切口：{angle}。情绪：{mood}。\n"
                f"{brief or hook or '顾帧按这个切口出图。'}\n"
                f"下一步：{next_step}。"
            )
            await self._say(AgentRole.STRATEGY, state, text, reply=True)
            wf.log(f"切口 {angle} / {film} / {job}")
            self.store.save(wf)
            return {
                **state,
                "workflow": _dump(wf),
                "film_name": film,
                "angle": angle,
                "mood": mood,
                "brief": brief,
                "hook": hook,
                "job": job,
            }

        async def visual_node(state: HuddleState) -> HuddleState:
            wf = _wf(state)
            wf.status = WorkflowStatus.PRODUCING
            wf.log("Huddle → visual")
            job = str(state.get("job") or "poster")
            if job == "talk":
                reply = await _text_role(
                    "visual",
                    (
                        f"{_ctx_block()}"
                        "你是顾帧。老板没点名也要你接一句画面侧的话。不要生图、不要问主色。\n"
                        f"老板原话：{state.get('user_text')}\n2～3 句。禁止 <think>。"
                    ),
                )
                await self._say(
                    AgentRole.VISUAL,
                    state,
                    reply or "画面这边先搁着，老沈点头我再出。",
                    reply=False,
                )
                self.store.save(wf)
                return {**state, "workflow": _dump(wf)}
            logo = job == "logo"
            data = await _json_role(
                "visual",
                (
                    "总编已经定方向，你是顾帧，立刻出图，禁止再问情绪/公司名/主色。"
                    "禁止另起一套方案，禁止让老板在科技风/电影感里二选一。缺的信息按 MatrixSolo 影视工作室补齐。\n"
                    f"任务：{'公司 logo' if logo else '电影宣发海报'}\n"
                    f"主题：{state.get('film_name')}\n切口：{state.get('angle')}\n"
                    f"情绪：{state.get('mood')}\n钩子：{state.get('hook')}\n方向：{state.get('brief')}\n"
                    f"老板原话：{state.get('user_text')}\n"
                    "输出 JSON：{\"prompt\":\"可直接生图的画面描述\","
                    "\"mood\":\"情绪\",\"aspect_ratio\":\"1:1或16:9\"}"
                    + (
                        "。logo 要求：简洁矢量感、可缩成头像、不要小字、不要复杂场景。"
                        if logo
                        else "。海报要求：含构图和顶部18%标题安全区。"
                    )
                ),
            )
            default_ratio = "1:1" if logo else "16:9"
            prompt = str(data.get("prompt") or "").strip() or (
                f"{state.get('film_name')} {'minimal brand logo, vector, flat, high contrast'
                if logo else 'movie poster, cinematic, title safe top 18%'}"
                f", {state.get('angle')}, {state.get('mood')}"
            )
            ratio = str(data.get("aspect_ratio") or default_ratio).strip() or default_ratio
            mood = str(data.get("mood") or state.get("mood") or "").strip()
            from matrixsolo.admin.store import get_profile_store

            profile = get_profile_store().get("visual")
            paths: list[str] = []
            error = ""
            if can_image_gen(profile):
                ran = await self.runtime.image_gen(prompt, aspect_ratio=ratio)
                paths = [str(p) for p in (ran.get("paths") or []) if p]
                if not ran.get("ok"):
                    error = str(ran.get("error") or "生图失败")
            else:
                error = "视觉岗未启用生图"

            covers = [
                CoverVariant(
                    label="huddle",
                    prompt=prompt,
                    mood=mood,
                    image_path=paths[0] if paths else None,
                )
            ]
            wf.covers = covers
            if paths:
                extra = " 头像尺寸也认得。" if logo else " 顶部安全区留好了。"
                caption = f"按老沈的「{state.get('angle')}」出了。{mood}。{extra}"
            else:
                caption = f"图没出成：{error or '未知错误'}。"
            await self._say(AgentRole.VISUAL, state, caption, images=paths, reply=False)
            wf.log(f"海报 {len(paths)} 张" + (f" / {error}" if error else ""))
            self.store.save(wf)
            return {
                **state,
                "workflow": _dump(wf),
                "poster_prompt": prompt,
                "aspect_ratio": ratio,
                "image_paths": paths,
            }

        async def script_node(state: HuddleState) -> HuddleState:
            wf = _wf(state)
            wf.log("Huddle → script")
            job = str(state.get("job") or "poster")
            if job == "talk":
                reply = await _text_role(
                    "script",
                    (
                        f"{_ctx_block()}"
                        "你是林钩。老板没点名也要你接一句文案侧的话。禁止调生图、禁止 JSON。\n"
                        f"老板原话：{state.get('user_text')}\n2～3 句。禁止 <think>。"
                    ),
                )
            else:
                reply = await _text_role(
                    "script",
                    (
                        "你是林钩。顾帧已经出图，你只补字，禁止调生图、禁止输出 JSON、禁止重开一套品牌讨论。\n"
                        f"任务：{'品牌 slogan / 中英锁定' if job == 'logo' else '封面标题/Hook'}\n"
                        f"主题：{state.get('film_name')} 切口：{state.get('angle')} 情绪：{state.get('mood')}\n"
                        "2～5 句。禁止 <think>。"
                    ),
                )
            await self._say(
                AgentRole.SCRIPT,
                state,
                reply or "字我来锁。画面归顾帧，别抢。",
                reply=False,
            )
            self.store.save(wf)
            return {**state, "workflow": _dump(wf)}

        async def editor_node(state: HuddleState) -> HuddleState:
            wf = _wf(state)
            wf.log("Huddle → editor")
            job = str(state.get("job") or "poster")
            if job == "talk":
                reply = await _text_role(
                    "editor",
                    (
                        f"{_ctx_block()}"
                        "你是阿刀。老板没点名也要你接一句成片侧的话。不要布置新剪辑任务。\n"
                        f"老板原话：{state.get('user_text')}\n2～3 句。禁止 <think>。"
                    ),
                )
            else:
                reply = await _text_role(
                    "editor",
                    (
                        "你是阿刀。总编和顾帧已经把海报方向定了，你只说成片侧能不能接，不要抢出图。\n"
                        f"主题：{state.get('film_name')} 切口：{state.get('angle')} "
                        f"画幅：{state.get('aspect_ratio') or '16:9'}\n"
                        "2～4 句。给横竖版和后续要轴的时间。禁止 <think>。"
                    ),
                )
            await self._say(AgentRole.EDITOR, state, reply or "海报定了就能粗剪。给我轴，横版先出。", reply=False)
            self.store.save(wf)
            return {**state, "workflow": _dump(wf)}

        async def ops_node(state: HuddleState) -> HuddleState:
            wf = _wf(state)
            wf.log("Huddle → ops")
            job = str(state.get("job") or "poster")
            if job == "talk":
                reply = await _text_role(
                    "ops",
                    (
                        f"{_ctx_block()}"
                        "你是周航。老板没点名也要你接一句排期/平台侧的话。不要改画面。\n"
                        f"老板原话：{state.get('user_text')}\n2～3 句。禁止 <think>。"
                    ),
                )
            else:
                reply = await _text_role(
                    "ops",
                    (
                        "你是周航。海报即将/已经出，你只说平台裁切和排期，不要改画面。\n"
                        f"主题：{state.get('film_name')}\n2～3 句。禁止 <think>。"
                    ),
                )
            await self._say(AgentRole.OPS, state, reply or "先发 B 站封面 16:9，抖音再压竖版。", reply=False)
            self.store.save(wf)
            return {**state, "workflow": _dump(wf)}

        async def finish_node(state: HuddleState) -> HuddleState:
            wf = _wf(state)
            wf.status = WorkflowStatus.COMPLETED
            wf.log("Huddle 完成")
            self.store.save(wf)
            return {**state, "workflow": _dump(wf)}

        g.add_node("brief", brief_node)
        g.add_node("visual", visual_node)
        g.add_node("script", script_node)
        g.add_node("editor", editor_node)
        g.add_node("ops", ops_node)
        g.add_node("finish", finish_node)
        g.add_edge(START, "brief")

        def after_brief(state: HuddleState) -> str:
            if state.get("need_visual"):
                return "visual"
            if state.get("need_script"):
                return "script"
            if state.get("need_editor"):
                return "editor"
            if state.get("need_ops"):
                return "ops"
            return "finish"

        def after_visual(state: HuddleState) -> str:
            if state.get("need_script"):
                return "script"
            if state.get("need_editor"):
                return "editor"
            if state.get("need_ops"):
                return "ops"
            return "finish"

        def after_script(state: HuddleState) -> str:
            if state.get("need_editor"):
                return "editor"
            if state.get("need_ops"):
                return "ops"
            return "finish"

        def after_editor(state: HuddleState) -> str:
            if state.get("need_ops"):
                return "ops"
            return "finish"

        g.add_conditional_edges(
            "brief",
            after_brief,
            {
                "visual": "visual",
                "script": "script",
                "editor": "editor",
                "ops": "ops",
                "finish": "finish",
            },
        )
        g.add_conditional_edges(
            "visual",
            after_visual,
            {
                "script": "script",
                "editor": "editor",
                "ops": "ops",
                "finish": "finish",
            },
        )
        g.add_conditional_edges(
            "script",
            after_script,
            {"editor": "editor", "ops": "ops", "finish": "finish"},
        )
        g.add_conditional_edges(
            "editor",
            after_editor,
            {"ops": "ops", "finish": "finish"},
        )
        g.add_edge("ops", "finish")
        g.add_edge("finish", END)
        return g.compile()

    async def _say(
        self,
        role: AgentRole,
        state: HuddleState,
        text: str,
        *,
        images: list[str] | None = None,
        reply: bool,
    ) -> None:
        text = strip_think(text or "").strip()
        chat_id = state.get("chat_id") or ""
        message_id = state.get("message_id") or ""
        if text:
            sent = False
            if reply and message_id:
                sent = await self.feishu.reply_text(message_id, text, role=role)
            if not sent and chat_id:
                await self.feishu.send_text(chat_id, text, role=role)
        for path in images or []:
            if chat_id:
                ok = await self.feishu.send_image(chat_id, path, role=role)
                if not ok and message_id:
                    await self.feishu.reply_image(message_id, path, role=role)

    async def run(
        self,
        *,
        user_text: str,
        chat_id: str,
        message_id: str,
        need_visual: bool = True,
        need_script: bool = True,
        need_editor: bool = True,
        need_ops: bool = True,
        job: str = "poster",
    ) -> WorkflowState:
        wf = WorkflowState(trigger="feishu_huddle")
        wf.log("飞书 huddle 启动")
        self.store.save(wf)
        result = await self._graph.ainvoke(
            {
                "workflow": _dump(wf),
                "user_text": user_text,
                "chat_id": chat_id,
                "message_id": message_id,
                "need_visual": need_visual,
                "need_script": need_script,
                "need_editor": need_editor,
                "need_ops": need_ops,
                "job": job,
                "image_paths": [],
            }
        )
        done = _wf(result)
        save_studio_context(
            chat_id=chat_id,
            workflow_id=done.workflow_id,
            job=str(result.get("job") or job),
            film_name=str(result.get("film_name") or (done.selected_topic.film_name if done.selected_topic else "")),
            angle=str(result.get("angle") or ""),
            mood=str(result.get("mood") or ""),
            brief=str(result.get("brief") or ""),
            hook=str(result.get("hook") or ""),
            user_text=user_text,
            image_paths=list(result.get("image_paths") or []),
        )
        job_name = str(result.get("job") or job)
        film = str(result.get("film_name") or "")
        from matrixsolo.admin.work_logs import record_work_log

        await record_work_log(
            project=film or "矩阵日常 huddle",
            work_type="huddle",
            status="done",
            summary=f"{job_name} huddle 完成：{result.get('angle') or ''} / {result.get('mood') or ''}",
            workflow_id=done.workflow_id,
            chat_id=chat_id,
            stage="huddle",
            employee_id="strategy",
            employee_title="总编",
            extra={"job": job_name, "film": film},
        )
        if job_name in {"logo", "poster"} and film:
            from datetime import date

            rows = [
                {
                    "film": film,
                    "slot": "18:00",
                    "date": date.today().isoformat(),
                    "potential": 0,
                    "reason": str(result.get("brief") or result.get("angle") or job_name),
                }
            ]
            append_calendar_rows(rows)
            try:
                await self.feishu.write_calendar(rows)
            except Exception:  # noqa: BLE001
                logger.exception("huddle calendar write failed")
        return done


async def _json_role(role: str, content: str) -> dict[str, Any]:
    gateway = get_gateway()
    data = await gateway.chat_for_role(
        role,
        [{"role": "user", "content": content}],
        kind=TaskKind.CREATIVE,
        as_json=True,
    )
    return data if isinstance(data, dict) else {}


async def _text_role(role: str, content: str) -> str:
    gateway = get_gateway()
    raw = await gateway.chat_for_role(
        role,
        [{"role": "user", "content": content}],
        kind=TaskKind.CREATIVE,
        as_json=False,
    )
    return strip_think(str(raw or "").strip())


async def run_studio_huddle(
    *,
    user_text: str,
    chat_id: str,
    message_id: str,
    mentioned: set[AgentRole],
) -> WorkflowState:
    _ = mentioned
    text = user_text or ""
    huddle = StudioHuddle()
    return await huddle.run(
        user_text=text,
        chat_id=chat_id,
        message_id=message_id,
        need_visual=True,
        need_script=True,
        need_editor=True,
        need_ops=True,
        job=huddle_job(text),
    )
