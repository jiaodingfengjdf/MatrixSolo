from __future__ import annotations

from datetime import datetime, timedelta, timezone

from matrixsolo.agents.base import load_profile, require_tool
from matrixsolo.gateway import TaskKind, get_gateway
from matrixsolo.models import DistributionPackage, WorkflowState


GOLDEN_SLOTS = {
    "morning": (7, 0),
    "noon": (12, 0),
    "evening": (18, 0),
}

PLATFORM_ALIASES = {
    "douyin": "douyin",
    "抖音": "douyin",
    "dy": "douyin",
    "bilibili": "bilibili",
    "b站": "bilibili",
    "哔哩哔哩": "bilibili",
    "bili": "bilibili",
    "toutiao": "toutiao",
    "头条": "toutiao",
    "今日头条": "toutiao",
}


class OperationsAgent:
    """运营/发布员：元数据封装、排期分发、互动冷启动话术."""

    def __init__(self) -> None:
        self.gateway = get_gateway()

    async def package_and_schedule(self, state: WorkflowState) -> WorkflowState:
        profile = load_profile("ops")
        if not profile.enabled:
            state.errors.append("运营 Agent 已禁用")
            return state
        if not require_tool(profile, "distribute"):
            state.log("运营 Agent：distribute 未启用，跳过")
            return state
        if not state.script or not state.selected_topic:
            state.errors.append("运营 Agent：缺少脚本或选题")
            return state

        state.log("运营 Agent：封装多平台元数据并排期")
        title = state.script.selected_title or state.script.titles[0]
        data = await self.gateway.chat_for_role(
            "ops",
            [
                {
                    "role": "user",
                    "content": (
                        f"主推标题: {title}\n"
                        f"影片: {state.selected_topic.film_name}\n"
                        f"Hook: {state.script.hook}\n"
                        f"形态: {state.content_form.value}\n"
                        "请输出 SEO 元数据 JSON。"
                    ),
                }
            ],
            kind=TaskKind.CLASSIFY,
            as_json=True,
        )
        assert isinstance(data, dict)

        now = datetime.now(timezone.utc) + timedelta(hours=8)
        packages: list[DistributionPackage] = []
        raw_packages = data.get("packages") or []
        if not raw_packages:
            raw_packages = [
                {
                    "platform": "douyin",
                    "title": title,
                    "description": state.script.hook,
                    "tags": ["电影解说", "影视"],
                },
                {
                    "platform": "bilibili",
                    "title": f"【解说】{title}",
                    "description": state.script.hook,
                    "tags": ["影视杂谈"],
                },
                {
                    "platform": "toutiao",
                    "title": title,
                    "description": state.script.hook,
                    "tags": ["电影"],
                },
            ]
        for item in raw_packages:
            platform = PLATFORM_ALIASES.get(str(item.get("platform") or "").strip().lower(), "douyin")
            hour, minute = GOLDEN_SLOTS["evening"]
            if platform == "toutiao":
                hour, minute = GOLDEN_SLOTS["morning"]
            scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if scheduled < now:
                scheduled = scheduled + timedelta(days=1)
            packages.append(
                DistributionPackage(
                    platform=platform,
                    title=str(item.get("title") or title),
                    description=str(item.get("description") or ""),
                    tags=[str(t) for t in item.get("tags") or []],
                    scheduled_at=scheduled,
                    status="queued",
                )
            )

        state.distributions = packages
        state.log(f"运营 Agent：已排期 {len(packages)} 个平台")
        return state

    def cold_start_comments(self, state: WorkflowState) -> list[str]:
        film = state.selected_topic.film_name if state.selected_topic else "这部电影"
        return [
            f"第一个发现彩蛋的扣 1：{film} 里最容易被忽略的细节是？",
            "你觉得结局是开放式还是早有定论？评论区聊聊。",
            "收藏慢慢看，下一期拆更狠的反转。",
        ]
