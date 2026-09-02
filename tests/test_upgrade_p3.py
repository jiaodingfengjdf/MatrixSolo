from __future__ import annotations

import asyncio

import pytest


def _reset_singletons() -> None:
    import matrixsolo.admin.departments as dp
    import matrixsolo.admin.digital_humans as dh
    import matrixsolo.admin.employees as emp
    import matrixsolo.admin.model_center as mc
    import matrixsolo.admin.store as st
    import matrixsolo.admin.work_logs as wl

    dh._store = None
    dp._store = None
    emp._store = None
    mc._store = None
    st._store = None
    wl._store = None


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MATRIXSOLO_DATA_DIR", str(tmp_path / "data"))
    from matrixsolo.config import get_settings

    get_settings.cache_clear()
    _reset_singletons()
    yield tmp_path / "data"
    get_settings.cache_clear()
    _reset_singletons()


def test_digital_human_store_and_employee_binding(data_dir):
    from matrixsolo.admin.digital_humans import (
        DigitalHumanCreate,
        DigitalHumanUpdate,
        get_digital_human_store,
    )
    from matrixsolo.admin.employees import EmployeeCreate, EmployeeUpdate, get_employee_store

    store = get_digital_human_store()
    assert store.get("default-voice") is not None
    asset = store.create(
        DigitalHumanCreate(
            id="avatar-a",
            name="形象A",
            voice_id="zh-CN-XiaoxiaoNeural",
            portrait_asset_id="asset_p_1",
            enabled=True,
        )
    )
    assert asset.id == "avatar-a"
    updated = store.update("avatar-a", DigitalHumanUpdate(provider="azure"))
    assert updated.provider == "azure"

    get_employee_store().create(
        EmployeeCreate(id="news_anchor", title="口播主播", app_id="a", app_secret="s")
    )
    bound = get_employee_store().update(
        "news_anchor",
        EmployeeUpdate(digital_human_id="avatar-a", digital_human_enabled=True),
    )
    assert bound.digital_human_id == "avatar-a"
    assert bound.digital_human_enabled is True
    store.delete("avatar-a")
    assert store.get("avatar-a") is None


def test_gateway_capability_fallbacks(data_dir):
    from matrixsolo.admin.work_logs import get_work_log_store
    from matrixsolo.gateway import CapabilityUnavailable, get_gateway

    gateway = get_gateway()
    assert gateway.has_capability("video") is False
    assert gateway.has_capability("text") is True

    # 无 vision 密钥 → 明确抛 CapabilityUnavailable，不静默
    with pytest.raises(CapabilityUnavailable):
        asyncio.run(gateway.complete_vision([{"role": "user", "content": "看封面"}], ["x.png"]))

    # 未配置 video → 任务失败且工作记录可见
    result = asyncio.run(
        gateway.generate_video(prompt="风雪电影海报", workflow_id="wf-v1", project="测试视频")
    )
    assert result["status"] == "failed"
    assert result["task_id"].startswith("video-")
    rows = get_work_log_store().list(work_type="workflow")
    assert any(r.stage == "video" and r.status == "failed" for r in rows)

    # TTS 样片在 pytest 下安全跳过真实合成
    tts = asyncio.run(gateway.synthesize_speech("开场三秒先抛冲突。"))
    assert tts["ok"] is True


def test_complete_text_alias(data_dir):
    from matrixsolo.gateway import get_gateway

    out = asyncio.run(
        get_gateway().complete_text(
            [{"role": "user", "content": "hello"}],
            kind="creative",
            provider="grsai",
        )
    )
    assert isinstance(out, str) and out
