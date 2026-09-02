from __future__ import annotations

import pytest

from matrixsolo.feishu.chat import (
    event_to_payload,
    extract_mentioned_roles,
    huddle_claim_id,
    huddle_leader,
    message_stamp,
    should_huddle,
    try_claim_huddle,
)
from matrixsolo.feishu.staff import AgentRole


def test_huddle_when_multiple_staff_mentioned():
    message = {
        "content": '{"text":"@总编 @剪辑 @视觉 今天正式开工，先做一张海报，自然与人"}',
        "mentions": [{"name": "总编"}, {"name": "剪辑"}, {"name": "视觉"}],
    }
    mentioned = extract_mentioned_roles(message)
    assert mentioned == {AgentRole.STRATEGY, AgentRole.EDITOR, AgentRole.VISUAL}
    assert should_huddle(mentioned, "今天正式开工，先做一张海报，自然与人")
    assert huddle_leader(mentioned) == AgentRole.STRATEGY


def test_single_visual_image_is_not_huddle():
    mentioned = {AgentRole.VISUAL}
    assert not should_huddle(mentioned, "生图一张赛博封面")
    assert huddle_leader(mentioned) == AgentRole.VISUAL


def test_kickoff_without_mentions_is_huddle():
    assert should_huddle(set(), "今天正式开工，为我们的公司设计专属logo")
    assert should_huddle(set(), "很好 大家先下班今天")


def test_huddle_job_skips_image_on_casual_chat():
    from matrixsolo.orchestration.huddle import huddle_job

    assert huddle_job("为我们的公司设计专属 logo") == "logo"
    assert huddle_job("先做一张海报") == "poster"
    assert huddle_job("很好 大家先下班今天") == "talk"


def test_studio_memory_shared_across_roles(tmp_path, monkeypatch):
    from matrixsolo import config as cfg
    from matrixsolo.admin.studio_memory import (
        append_calendar_rows,
        format_studio_context,
        recent_calendar,
        save_studio_context,
    )

    settings = cfg.get_settings()
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    save_studio_context(
        chat_id="oc_1",
        workflow_id="w1",
        job="logo",
        film_name="MatrixSolo",
        angle="稳重科技",
        mood="冷蓝",
        user_text="设计专属 logo",
        image_paths=["a.png"],
    )
    blob = format_studio_context()
    assert "MatrixSolo" in blob
    assert "稳重科技" in blob
    append_calendar_rows([{"film": "MatrixSolo", "slot": "18:00", "date": "2026-09-02"}])
    rows = recent_calendar()
    assert rows and rows[0]["film"] == "MatrixSolo"


@pytest.mark.asyncio
async def test_calendar_rows_have_slots():
    from matrixsolo.agents.strategy import StrategyAgent
    from matrixsolo.models import TopicCandidate

    agent = StrategyAgent()
    rows = await agent.write_calendar_rows(
        [TopicCandidate(film_name="盗梦空间", reason="梦", potential_score=8.0)]
    )
    assert rows[0]["slot"] in {"07:00", "18:00"}
    assert rows[0]["film"] == "盗梦空间"


@pytest.mark.asyncio
async def test_compose_still_video_without_media(tmp_path):
    from matrixsolo.assets.compose import compose_still_video

    ok = await compose_still_video(
        cover=tmp_path / "missing.png",
        audio=tmp_path / "missing.mp3",
        subtitle=None,
        preview=tmp_path / "p.mp4",
        final=tmp_path / "f.mp4",
    )
    assert ok is False


def test_same_user_text_shares_huddle_claim(tmp_path, monkeypatch):
    from matrixsolo import config as cfg

    settings = cfg.get_settings()
    monkeypatch.setattr(settings, "data_dir", tmp_path)

    text = "今天正式开工，为我们的公司设计专属 logo"
    chat = "oc_abc"
    a = huddle_claim_id(chat, "om_visual", text)
    b = huddle_claim_id(chat, "om_script", text)
    c = huddle_claim_id(chat, "om_strategy", text)
    assert a == b == c
    assert message_stamp(chat, "om_1", text) == "msg:om_1"
    assert try_claim_huddle(a, "strategy")
    assert not try_claim_huddle(b, "visual")


def test_event_to_payload_reads_sdk_objects():
    from types import SimpleNamespace

    data = SimpleNamespace(
        header=SimpleNamespace(event_id="evt-1"),
        event=SimpleNamespace(
            sender=SimpleNamespace(
                sender_type="user",
                sender_id=SimpleNamespace(open_id="ou_1", user_id="u1"),
            ),
            message=SimpleNamespace(
                chat_id="oc_1",
                message_id="om_1",
                message_type="text",
                content='{"text":"@总编 开工"}',
                mentions=[SimpleNamespace(name="总编", key="@_user_1")],
            ),
        ),
    )
    payload = event_to_payload(data, "cli_test")
    assert payload["event"]["message"]["message_id"] == "om_1"
    assert payload["event"]["message"]["mentions"][0]["name"] == "总编"
    assert payload["event"]["sender"]["sender_id"] == "ou_1"
    message = {
        "content": '{"text":"@_user_1 @_user_2 开工做 logo"}',
        "mentions": [{"name": "MatrixSolo视觉"}, {"name": "MatrixSolo总编"}],
    }
    mentioned = extract_mentioned_roles(message)
    assert AgentRole.VISUAL in mentioned
    assert AgentRole.STRATEGY in mentioned


def test_card_action_payload_and_btn_values():
    from types import SimpleNamespace

    from matrixsolo.feishu.chat import card_action_to_payload, extract_card_value
    from matrixsolo.feishu.hitl import _btn

    value = _btn(workflow_id="w1", stage="topic", action="pass", index=0)
    assert value == {
        "workflow_id": "w1",
        "stage": "topic",
        "action": "pass",
        "index": "0",
    }
    http = {
        "header": {"event_type": "card.action.trigger"},
        "event": {"action": {"value": value}},
    }
    assert extract_card_value(http)["action"] == "pass"
    data = SimpleNamespace(
        event=SimpleNamespace(action=SimpleNamespace(value={"workflow_id": "w1", "stage": "script", "action": "pass"}))
    )
    payload = card_action_to_payload(data, "cli_x")
    assert payload["kind"] == "card_action"
    assert payload["value"]["stage"] == "script"

