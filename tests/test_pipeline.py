from __future__ import annotations

import pytest

from matrixsolo.admin.models import McpServerCreate, McpServerUpdate, PromptSkillCreate
from matrixsolo.admin.store import ProfileStore
from matrixsolo.analytics import ReviewEngine
from matrixsolo.models import ContentForm, WorkflowState
from matrixsolo.orchestration import ProductionOrchestrator
from matrixsolo.safety import ContentSafetyEngine


@pytest.fixture()
def profile_store(tmp_path):
    return ProfileStore(path=tmp_path / "agent_profiles.json")


@pytest.mark.asyncio
async def test_end_to_end_demo_pipeline():
    orch = ProductionOrchestrator()
    state = await orch.start(trigger="test", content_form="逐帧解说")
    assert state.topics
    assert state.status.value == "awaiting_topic_approval"
    state = await orch.auto_approve_demo(state.workflow_id)
    assert state.status.value == "completed"
    assert state.script is not None
    assert state.script.selected_title
    assert state.render is not None
    assert state.distributions


@pytest.mark.asyncio
async def test_sensitive_word_replacement():
    engine = ContentSafetyEngine()
    result = engine.static_filter("这场杀戮带来了暴利")
    assert "击溃" in result.text
    assert "可观收益" in result.text
    assert result.level == 1


def test_review_engine_insights():
    engine = ReviewEngine()
    insights = engine.analyze(
        {"retention_5s": 0.4, "completion_rate": 0.5, "ctr": 0.03, "follow_rate": 0.02}
    )
    names = {i.name for i in insights}
    assert "retention_5s" in names
    assert "ctr" in names


def test_workflow_state_defaults():
    state = WorkflowState()
    assert state.content_form == ContentForm.FRAME_BY_FRAME
    state.log("hello")
    assert state.logs


def test_profile_mcp_and_skills_crud(profile_store: ProfileStore):
    role = "editor"
    profile = profile_store.get(role)
    assert profile.title == "剪辑"
    assert any(m.name == "LocalEditExecutor" for m in profile.mcp_servers)

    updated = profile_store.add_mcp(
        role,
        McpServerCreate(
            name="TestMCP",
            transport="http",
            url="http://127.0.0.1:9999",
            enabled=True,
        ),
    )
    mcp_id = next(m.id for m in updated.mcp_servers if m.name == "TestMCP")
    updated = profile_store.update_mcp(role, mcp_id, McpServerUpdate(enabled=False))
    assert any(m.id == mcp_id and not m.enabled for m in updated.mcp_servers)
    updated = profile_store.delete_mcp(role, mcp_id)
    assert all(m.name != "TestMCP" for m in updated.mcp_servers)

    updated = profile_store.add_skill(
        role, PromptSkillCreate(name="节奏", content="转场不超过 1.2s")
    )
    skill_id = next(s.id for s in updated.skills if s.name == "节奏")
    updated = profile_store.delete_skill(role, skill_id)
    assert all(s.name != "节奏" for s in updated.skills)


def test_persona_system_prompt_covers_voice_and_boundary():
    from matrixsolo.admin.defaults import default_profiles
    from matrixsolo.admin.personas import PERSONAS

    profiles = default_profiles()
    assert set(profiles) == set(PERSONAS)
    for role, profile in profiles.items():
        text = profile.composed_system_prompt()
        assert "活人感守则" in text
        assert profile.personality
        assert profile.craft
        assert profile.work_style
        assert profile.memory
        assert "不可做" in profile.capability_boundary
        assert profile.personality[:12] in text
        assert "能力边界" in text
        assert profile.title in ("总编", "文案", "视觉", "剪辑", "运营")
        dumped = profile.dump_admin()
        assert dumped["composed_system_prompt"] == text
        assert "composed_system_prompt" not in profile.model_dump()
