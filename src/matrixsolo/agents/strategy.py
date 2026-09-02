from __future__ import annotations

from datetime import date, timedelta
from typing import Any
import logging

from matrixsolo.admin.studio_memory import append_calendar_rows
from matrixsolo.agents.base import load_profile, require_tool
from matrixsolo.feishu.client import FeishuClient
from matrixsolo.gateway import TaskKind, get_gateway
from matrixsolo.models import TopicCandidate, WorkflowState
from matrixsolo.rag import get_knowledge_store
from matrixsolo.skills.runtime import SkillRuntime

logger = logging.getLogger(__name__)


class HotRadar:
    """热榜雷达：走内置 SkillRuntime，失败时明确报源失败。"""

    def __init__(self) -> None:
        self.runtime = SkillRuntime()

    async def fetch(self) -> list[dict[str, Any]]:
        result = await self.runtime.hot_radar()
        items = list(result.get("items") or [])
        if items:
            return items
        logger_note = result.get("note") or "热榜源失败"
        return [{"name": logger_note, "heat": 0, "source": "hot_radar_error", "douban": 0}]


class StrategyAgent:
    """总编/策略官：热点监控、选题评估、排期决策."""

    def __init__(self) -> None:
        self.radar = HotRadar()
        self.gateway = get_gateway()
        self.rag = get_knowledge_store()

    async def propose_topics(self, state: WorkflowState) -> WorkflowState:
        profile = load_profile("strategy")
        if not profile.enabled:
            state.errors.append("总编 Agent 已禁用")
            return state

        state.log("总编 Agent：启动热榜雷达")
        hot = await self.radar.fetch() if require_tool(profile, "hot_radar") else []
        viral_ctx = ""
        if require_tool(profile, "rag"):
            viral_hits = self.rag.query("爆款选题 Hook 情绪张力", n_results=3)
            viral_ctx = "\n".join(h["text"] for h in viral_hits)

        data = await self.gateway.chat_for_role(
            "strategy",
            [
                {
                    "role": "user",
                    "content": (
                        f"目标受众: {state.audience_profile}\n"
                        f"内容形态: {state.content_form.value}\n"
                        f"热榜: {hot}\n"
                        f"历史爆款参考:\n{viral_ctx}\n"
                        f"自定义备注: {state.topic_custom_note or '无'}\n"
                        "请输出选题 JSON。"
                    ),
                }
            ],
            kind=TaskKind.CREATIVE,
            as_json=True,
        )
        assert isinstance(data, dict)
        topics: list[TopicCandidate] = []
        for item in data.get("topics") or []:
            topics.append(TopicCandidate(**item))
        topics.sort(key=lambda t: t.potential_score, reverse=True)
        state.topics = topics
        state.log(f"总编 Agent：生成 {len(topics)} 个选题候选")
        if topics:
            await self.publish_calendar(topics)
            state.log("总编 Agent：内容日历已写入")
        return state

    async def write_calendar_rows(self, topics: list[TopicCandidate]) -> list[dict[str, Any]]:
        rows = []
        slots = ["07:00", "18:00"]
        today = date.today()
        for i, topic in enumerate(topics[:6]):
            day = today + timedelta(days=i // 2)
            rows.append(
                {
                    "film": topic.film_name,
                    "slot": slots[i % 2],
                    "date": day.isoformat(),
                    "potential": topic.potential_score,
                    "reason": topic.reason,
                }
            )
        return rows

    async def publish_calendar(self, topics: list[TopicCandidate]) -> list[dict[str, Any]]:
        rows = await self.write_calendar_rows(topics)
        append_calendar_rows(rows)
        try:
            await FeishuClient().write_calendar(rows)
        except Exception:  # noqa: BLE001
            logger.exception("Feishu calendar write failed")
        return rows
