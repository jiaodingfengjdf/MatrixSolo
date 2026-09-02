from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WorkflowStatus(str, Enum):
    PENDING = "pending"
    STRATEGY = "strategy"
    AWAITING_TOPIC_APPROVAL = "awaiting_topic_approval"
    SCRIPTING = "scripting"
    AWAITING_SCRIPT_APPROVAL = "awaiting_script_approval"
    PRODUCING = "producing"
    RENDERING = "rendering"
    AWAITING_FINAL_APPROVAL = "awaiting_final_approval"
    DISTRIBUTING = "distributing"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ContentForm(str, Enum):
    FRAME_BY_FRAME = "逐帧解说"
    MONTAGE = "混剪盘点"
    REVIEW = "影评漫谈"
    BEHIND_SCENES = "幕后花絮"


class HitlAction(str, Enum):
    PASS = "pass"
    REJECT = "reject"
    REROLL = "reroll"
    CUSTOM = "custom"
    SELECT_TITLE = "select_title"
    PUBLISH_NOW = "publish_now"
    REEDIT = "reedit"
    SCHEDULE = "schedule"


class TopicCandidate(BaseModel):
    film_name: str
    douban_score: float | None = None
    reason: str
    hook_points: list[str] = Field(default_factory=list)
    heat_index: float = 0.0
    emotion_score: float = 0.0
    audience_breadth: float = 0.0
    material_richness: float = 0.0
    potential_score: float = 0.0
    source: str = "hot_radar"
    raw: dict[str, Any] = Field(default_factory=dict)


class ScriptDraft(BaseModel):
    form: ContentForm = ContentForm.FRAME_BY_FRAME
    hook: str
    body: str
    titles: list[str] = Field(default_factory=list)
    selected_title: str | None = None
    article_markdown: str | None = None
    fact_notes: list[str] = Field(default_factory=list)
    safety_replacements: list[dict[str, str]] = Field(default_factory=list)


class CoverVariant(BaseModel):
    label: str
    prompt: str
    mood: str
    image_path: str | None = None
    image_url: str | None = None


class AudioAsset(BaseModel):
    path: str
    duration_sec: float = 0.0
    word_boundaries: list[dict[str, Any]] = Field(default_factory=list)
    ass_subtitle_path: str | None = None


class RenderResult(BaseModel):
    preview_url: str | None = None
    preview_path: str | None = None
    final_path: str | None = None
    compliance_score: float = 1.0
    compliance_report: dict[str, Any] = Field(default_factory=dict)
    md5: str | None = None


class DistributionPackage(BaseModel):
    platform: Literal["douyin", "bilibili", "toutiao"]
    title: str
    description: str
    tags: list[str] = Field(default_factory=list)
    scheduled_at: datetime | None = None
    status: str = "queued"


class WorkflowState(BaseModel):
    workflow_id: str = Field(default_factory=lambda: str(uuid4()))
    status: WorkflowStatus = WorkflowStatus.PENDING
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    trigger: str = "manual"
    audience_profile: str = "泛影视爱好者 / 都市白领"
    content_form: ContentForm = ContentForm.FRAME_BY_FRAME
    department_id: str = "default"
    department_name: str = "默认"
    hitl_chat_id: str = ""

    topics: list[TopicCandidate] = Field(default_factory=list)
    selected_topic: TopicCandidate | None = None
    topic_custom_note: str | None = None

    script: ScriptDraft | None = None
    covers: list[CoverVariant] = Field(default_factory=list)
    audio: AudioAsset | None = None
    render: RenderResult | None = None
    distributions: list[DistributionPackage] = Field(default_factory=list)

    hitl_topic_action: HitlAction | None = None
    hitl_script_action: HitlAction | None = None
    hitl_final_action: HitlAction | None = None

    safety_level: int = 0
    safety_messages: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    logs: list[str] = Field(default_factory=list)

    film_id: str | None = None
    asset_dir: str | None = None
    feishu_message_ids: dict[str, str] = Field(default_factory=dict)

    def log(self, message: str) -> None:
        stamp = utcnow().isoformat(timespec="seconds")
        self.logs.append(f"[{stamp}] {message}")
        self.updated_at = utcnow()
