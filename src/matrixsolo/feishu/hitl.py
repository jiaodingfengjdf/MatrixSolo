from __future__ import annotations

from typing import Any

from matrixsolo.config import get_settings
from matrixsolo.feishu.client import FeishuClient
from matrixsolo.feishu.staff import AgentRole, ROLE_TITLES
from matrixsolo.models import WorkflowState


def _btn(**fields: Any) -> dict[str, str]:
    """飞书卡片 value 必须全是字符串，否则 SDK/回传会丢字段。"""
    return {str(k): str(v) for k, v in fields.items() if v is not None}


class HitlCards:
    """飞书人机回环交互卡片：由对应岗位 AI 员工发出."""

    def __init__(self, client: FeishuClient | None = None) -> None:
        self.client = client or FeishuClient()
        self.settings = get_settings()

    async def _send(self, card: dict[str, Any], role: AgentRole) -> str | None:
        # 卡片标题前缀岗位名，便于群内识别发言人
        header = card.get("header") or {}
        title = (header.get("title") or {}).get("content") or ""
        staff_title = ROLE_TITLES[role]
        if staff_title not in title:
            header = {
                **header,
                "title": {
                    "tag": "plain_text",
                    "content": f"【{staff_title}】{title}",
                },
            }
            card = {**card, "header": header}

        chat_id = self.settings.feishu_hitl_chat_id
        if not chat_id:
            return await self.client.send_interactive("local", card, role=role)
        return await self.client.send_interactive(chat_id, card, role=role)

    async def send_topic_card(self, state: WorkflowState) -> str | None:
        elements: list[dict[str, Any]] = []
        for i, t in enumerate(state.topics[:3]):
            elements.append(
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"**{i+1}. {t.film_name}**  豆瓣 {t.douban_score or '-'} | "
                            f"潜力 {t.potential_score:.1f}\n"
                            f"理由：{t.reason}\n"
                            f"爆款点：{', '.join(t.hook_points)}"
                        ),
                    },
                }
            )
        elements.append(
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "通过选题1"},
                        "type": "primary",
                        "value": _btn(
                            workflow_id=state.workflow_id,
                            stage="topic",
                            action="pass",
                            index=0,
                        ),
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "换一批"},
                        "type": "default",
                        "value": _btn(
                            workflow_id=state.workflow_id,
                            stage="topic",
                            action="reroll",
                        ),
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "自定义输入"},
                        "type": "danger",
                        "value": _btn(
                            workflow_id=state.workflow_id,
                            stage="topic",
                            action="custom",
                        ),
                    },
                ],
            }
        )
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "blue",
                "title": {"tag": "plain_text", "content": "HITL1 · 选题审批"},
            },
            "elements": elements,
        }
        return await self._send(card, AgentRole.STRATEGY)

    async def send_script_card(self, state: WorkflowState) -> str | None:
        script = state.script
        if not script:
            return None
        hook_lines = script.hook.strip().split("。")[:3]
        hook_preview = "。".join([x for x in hook_lines if x])
        titles_md = "\n".join(f"{i+1}. {t}" for i, t in enumerate(script.titles))
        notes = ""
        if script.fact_notes:
            notes = "\n\n⚠️ 事实存疑：\n" + "\n".join(f"- {n}" for n in script.fact_notes)
        if script.safety_replacements:
            notes += "\n\n敏感词替换：" + ", ".join(
                f"{r['from']}→{r['to']}" for r in script.safety_replacements
            )
        elements = [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**Hook 前三句**\n{hook_preview}\n\n"
                        f"**正文（折叠预览）**\n{script.body[:280]}…"
                    ),
                },
            },
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**5 组备选标题**\n{titles_md}{notes}"},
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": f"选用标题{i+1}"},
                        "type": "primary" if i == 0 else "default",
                        "value": _btn(
                            workflow_id=state.workflow_id,
                            stage="script",
                            action="select_title",
                            title_index=i,
                        ),
                    }
                    for i in range(min(3, len(script.titles)))
                ],
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "通过（默认标题1）"},
                        "type": "primary",
                        "value": _btn(
                            workflow_id=state.workflow_id,
                            stage="script",
                            action="pass",
                        ),
                    }
                ],
            },
        ]
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "turquoise",
                "title": {"tag": "plain_text", "content": "HITL2 · 文案审批"},
            },
            "elements": elements,
        }
        return await self._send(card, AgentRole.SCRIPT)

    async def send_cover_notice(self, state: WorkflowState) -> str | None:
        """视觉岗通知：封面 A/B 已生成."""
        if not state.covers:
            return None
        covers = "\n".join(
            f"- **{c.label}**（{c.mood}）`{c.image_path or c.prompt[:40]}`"
            for c in state.covers
        )
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "purple",
                "title": {"tag": "plain_text", "content": "封面 A/B 测试包已就绪"},
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"影片：**{(state.selected_topic.film_name if state.selected_topic else '-')}**\n"
                            f"{covers}"
                        ),
                    },
                }
            ],
        }
        return await self._send(card, AgentRole.VISUAL)

    async def send_final_card(self, state: WorkflowState) -> str | None:
        render = state.render
        covers = "\n".join(
            f"- {c.label} ({c.mood}): `{c.image_path}`" for c in state.covers
        )
        score = render.compliance_score if render else 0
        preview = (render.preview_path if render else "") or "N/A"
        note = "本地预览文件，点开工作流看板可看路径。"
        if preview.lower().endswith(".mp4"):
            try:
                from pathlib import Path

                size = Path(preview).stat().st_size if Path(preview).is_file() else 0
                if size > 2000:
                    note = "已生成口播静帧预览 mp4（封面 + TTS）。"
                else:
                    note = "预览仍是占位文件，本机需安装 ffmpeg 才会出成片。"
            except OSError:
                pass
        elements = [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**预览**: `{preview}`\n"
                        f"{note}\n"
                        f"**合规评分**: {score:.2f}\n"
                        f"**封面 A/B**:\n{covers or '无'}"
                    ),
                },
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "立即全网发布"},
                        "type": "primary",
                        "value": _btn(
                            workflow_id=state.workflow_id,
                            stage="final",
                            action="publish_now",
                        ),
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "微调重剪"},
                        "type": "default",
                        "value": _btn(
                            workflow_id=state.workflow_id,
                            stage="final",
                            action="reedit",
                        ),
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "加入排期队列"},
                        "type": "default",
                        "value": _btn(
                            workflow_id=state.workflow_id,
                            stage="final",
                            action="schedule",
                        ),
                    },
                ],
            },
        ]
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "green",
                "title": {"tag": "plain_text", "content": "HITL3 · 成片终审"},
            },
            "elements": elements,
        }
        # 成片由剪辑岗提交终审；发布动作由运营岗在通过后执行
        return await self._send(card, AgentRole.EDITOR)

    async def send_distribution_notice(self, state: WorkflowState) -> str | None:
        if not state.distributions:
            return None
        lines = "\n".join(
            f"- **{d.platform}** {d.title} @ {d.scheduled_at} [{d.status}]"
            for d in state.distributions
        )
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "orange",
                "title": {"tag": "plain_text", "content": "多平台排期已 encapsulation"},
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": lines},
                }
            ],
        }
        # fix typo in title
        card["header"]["title"]["content"] = "多平台排期已就绪"
        return await self._send(card, AgentRole.OPS)

    async def send_alert_card(self, state: WorkflowState) -> str | None:
        issues = "\n".join(f"- {x}" for x in state.safety_messages) or "高危内容"
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "red",
                "title": {"tag": "plain_text", "content": "一级阻断 · 合规告警"},
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"**workflow**: `{state.workflow_id}`\n"
                            f"**违规要点**:\n{issues}\n\n请人工干预后重新触发。"
                        ),
                    },
                }
            ],
        }
        return await self._send(card, AgentRole.SCRIPT)
