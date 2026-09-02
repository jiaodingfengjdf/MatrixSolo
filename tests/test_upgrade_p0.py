from __future__ import annotations

import asyncio
import json

import pytest


def _reset_p0_singletons() -> None:
    import matrixsolo.admin.model_center as mc
    import matrixsolo.admin.prompt_os as po
    import matrixsolo.admin.work_logs as wl

    mc._store = None
    po._studio = None
    po._versions = None
    wl._store = None


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MATRIXSOLO_DATA_DIR", str(tmp_path / "data"))
    from matrixsolo.config import get_settings

    get_settings.cache_clear()
    _reset_p0_singletons()
    yield tmp_path / "data"
    get_settings.cache_clear()
    _reset_p0_singletons()


def test_model_center_crud_and_masking(data_dir):
    from matrixsolo.admin.model_center import (
        ModelProviderCreate,
        ModelProviderUpdate,
        get_model_store,
    )

    store = get_model_store()
    # 内置 provider 只读展示
    providers = store.list_providers()
    ids = [p.id for p in providers]
    assert set(ids) >= {"grsai", "openai", "anthropic", "deepseek"}

    created = store.create_provider(
        ModelProviderCreate(
            id="myrelay",
            name="某某中转",
            base_url="https://relay.example.com/v1",
            auth_method="bearer",
            api_key="sk-1234567890abcd",
            protocol="openai",
        )
    )
    assert created.id == "myrelay"
    assert created.dump_admin()["api_key_masked"].startswith("sk-1")
    assert "api_key" not in created.dump_admin()

    # 未改密钥则不覆盖
    updated = store.update_provider(
        "myrelay",
        ModelProviderUpdate(name="中转2", api_key=None),
    )
    assert updated.name == "中转2"
    assert updated.api_key == "sk-1234567890abcd"

    # 内置不可删
    with pytest.raises(ValueError):
        store.delete_provider("grsai")

    # 删除自定义 provider
    store.delete_provider("myrelay")
    assert store.get_provider("myrelay") is None


def test_model_center_slots_capability(data_dir):
    from matrixsolo.admin.model_center import (
        ModelCapability,
        ModelSlotCreate,
        get_model_store,
    )

    store = get_model_store()
    store.create_slot(
        ModelSlotCreate(
            provider_id="grsai",
            model_id="gpt-image-2",
            display_name="生图",
            capability=[ModelCapability.IMAGE],
        )
    )
    assert store.supports_capability("grsai", ModelCapability.IMAGE)
    assert not store.supports_capability("grsai", ModelCapability.VIDEO)
    resolved = store.resolve_slot("grsai", capability=ModelCapability.IMAGE)
    assert resolved and resolved.model_id == "gpt-image-2"


def test_gateway_capability_and_alias(data_dir):
    from matrixsolo.gateway import get_gateway

    gateway = get_gateway()
    assert gateway.supports_capability("grsai", "text")
    # 未配置 key 时 probe 明确失败，不静默 mock（生产约束）
    result = asyncio.run(gateway.probe("grsai"))
    assert result["ok"] is False
    assert "Key" in result["error"]


def test_prompt_os_layered_contains_layers(data_dir):
    from matrixsolo.admin.models import AgentProfile, AgentRoleKey
    from matrixsolo.admin.prompt_os import compose_layered, estimate_tokens

    profile = AgentProfile(
        role=AgentRoleKey.STRATEGY,
        title="总编",
        identity="你叫沈策，总编。",
        craft="热榜解读。",
        system_prompt="管线：输出 JSON 选题。",
    )
    composed = compose_layered(profile)
    assert "L0 工作室" in composed
    assert "你叫沈策" in composed
    assert "任务契约 (L3)" in composed
    assert estimate_tokens(composed) > 0


def test_prompt_version_and_rollback(data_dir):
    from matrixsolo.admin.models import AgentProfilePatch
    from matrixsolo.admin.store import ProfileStore

    store = ProfileStore(path=data_dir / "agent_profiles.json")
    before = store.get("strategy").composed_system_prompt()
    updated = store.update(
        "strategy",
        AgentProfilePatch(identity="你叫沈策 v2。"),
    )
    assert "v2" in updated.identity
    versions = store.list_prompt_versions("strategy")
    assert versions and versions[-1]["source"] == "manual"
    # 无 persona 变化时不产生版本
    store.update("strategy", AgentProfilePatch(temperature=0.1))
    versions2 = store.list_prompt_versions("strategy")
    assert len(versions2) == len(versions)

    target = versions[-1]["version"]
    rolled = store.rollback_prompt("strategy", target)
    assert "v2" in rolled.identity
    assert rolled.composed_system_prompt().startswith("## 活人感守则")
    assert before != rolled.composed_system_prompt()


def test_work_logs_idempotent_upsert(data_dir):
    from matrixsolo.admin.work_logs import WorkLog, WorkLogStore, business_today, make_log_id

    store = WorkLogStore(path=data_dir / "work_logs.jsonl")
    log_id = make_log_id(business_today(), "wf-1", "huddle", "huddle", "strategy")
    log1 = WorkLog(log_id=log_id, project="盗梦空间", work_type="huddle", status="done", summary="a")
    log2 = WorkLog(log_id=log_id, project="盗梦空间", work_type="huddle", status="done", summary="b")
    store.upsert(log1)
    store.upsert(log2)
    rows = store.list()
    assert len(rows) == 1
    assert rows[0].summary == "b"
    assert business_today().count("-") == 2


def test_record_work_log_local_only(data_dir):
    from matrixsolo.admin.work_logs import get_work_log_store, record_work_log

    log = asyncio.run(
        record_work_log(
            project="测试项目",
            work_type="workflow",
            status="done",
            summary="完成",
            workflow_id="wf-2",
            stage="distribute",
            employee_id="ops",
            employee_title="运营",
        )
    )
    assert log is not None
    rows = get_work_log_store().list()
    assert len(rows) == 1
    raw = (data_dir / "admin" / "work_logs.jsonl").read_text(encoding="utf-8")
    assert json.loads(raw.splitlines()[0])["log_id"] == log.log_id
