from __future__ import annotations

from matrixsolo.agents.base import load_profile, require_tool
from matrixsolo.gateway import TaskKind, get_gateway
from matrixsolo.models import ContentForm, ScriptDraft, WorkflowState, WorkflowStatus
from matrixsolo.rag import get_knowledge_store
from matrixsolo.safety import ContentSafetyEngine


FORM_PROMPTS = {
    ContentForm.FRAME_BY_FRAME: "逐帧解说：按时间轴切分，聚焦细节动作与隐喻剖析。",
    ContentForm.MONTAGE: "混剪盘点：强节奏排比，多部影片同类主题聚合。",
    ContentForm.REVIEW: "影评漫谈：主观视角叙事，侧重主旨、时代背景与导演风格。",
    ContentForm.BEHIND_SCENES: "幕后花絮：信息增量，原著对比、拍摄事故等未知细节。",
}


class ScriptwritingAgent:
    """文案/脚本匠：解说文案、Hook、标题 A/B、头条图文."""

    def __init__(self) -> None:
        self.gateway = get_gateway()
        self.rag = get_knowledge_store()
        self.safety = ContentSafetyEngine()

    async def write(self, state: WorkflowState) -> WorkflowState:
        profile = load_profile("script")
        if not profile.enabled:
            state.errors.append("文案 Agent 已禁用")
            return state

        topic = state.selected_topic
        if not topic:
            state.errors.append("文案 Agent：缺少已确认选题")
            return state

        state.log("文案 Agent：开始撰写脚本与图文")
        form_hint = FORM_PROMPTS.get(state.content_form, "")
        viral_ctx = fact_ctx = ""
        if require_tool(profile, "rag"):
            viral = self.rag.query(f"{topic.film_name} 爆款文案 Hook", n_results=3)
            viral_ctx = "\n".join(h["text"] for h in viral)
            facts = self.rag.query(topic.film_name, n_results=3)
            fact_ctx = "\n".join(h["text"] for h in facts)

        data = await self.gateway.chat_for_role(
            "script",
            [
                {
                    "role": "user",
                    "content": (
                        f"形态要求：{form_hint}\n"
                        f"影片: {topic.film_name}\n"
                        f"豆瓣: {topic.douban_score}\n"
                        f"推荐理由: {topic.reason}\n"
                        f"爆款点: {topic.hook_points}\n"
                        f"受众: {state.audience_profile}\n"
                        f"历史爆款:\n{viral_ctx}\n"
                        f"事实库:\n{fact_ctx}\n"
                        "请输出脚本 JSON。"
                    ),
                }
            ],
            kind=TaskKind.CREATIVE,
            as_json=True,
        )
        assert isinstance(data, dict)

        hook = str(data.get("hook") or "")
        body = str(data.get("body") or "")
        full_text = f"{hook}\n{body}"

        if require_tool(profile, "safety"):
            review = await self.safety.review(full_text, film_name=topic.film_name)
            if review.blocked:
                state.safety_level = 3
                state.safety_messages = review.issues
                state.status = WorkflowStatus.BLOCKED
                state.log("文案 Agent：合规一级阻断，等待人工干预")
                return state
            parts = review.text.split("\n", 1)
            safe_hook = parts[0]
            safe_body = parts[1] if len(parts) > 1 else ""
            fact_notes = review.fact_notes
            replacements = review.replacements
            state.safety_level = review.level
            state.safety_messages = review.issues
        else:
            safe_hook, safe_body = hook, body
            fact_notes, replacements = [], []

        titles = [str(t) for t in (data.get("titles") or [])][:5]
        while len(titles) < 5:
            titles.append(f"{topic.film_name}：你错过的细节 {len(titles)+1}")

        state.script = ScriptDraft(
            form=state.content_form,
            hook=safe_hook,
            body=safe_body,
            titles=titles,
            article_markdown=data.get("article_markdown"),
            fact_notes=fact_notes,
            safety_replacements=replacements,
        )
        state.log("文案 Agent：脚本与 5 组标题已生成")
        return state
