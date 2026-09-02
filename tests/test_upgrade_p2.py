from __future__ import annotations

import pytest


def _reset_singletons() -> None:
    import matrixsolo.admin.departments as dp
    import matrixsolo.admin.employees as emp
    import matrixsolo.admin.store as st

    dp._store = None
    emp._store = None
    st._store = None


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MATRIXSOLO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FEISHU_HITL_CHAT_ID", "oc_default")
    from matrixsolo.config import get_settings

    get_settings.cache_clear()
    _reset_singletons()
    yield tmp_path / "data"
    get_settings.cache_clear()
    _reset_singletons()


def test_department_store_presets_and_bind(data_dir):
    from matrixsolo.admin.departments import (
        DepartmentCreate,
        get_department_store,
    )

    store = get_department_store()
    ids = {d.id for d in store.list()}
    assert {"toutiao", "douyin", "bilibili"} <= ids
    toutiao = store.get("toutiao")
    assert "editor" not in toutiao.member_employee_ids

    bound = store.bind_chat("toutiao", "oc_toutiao")
    assert bound.chat_id == "oc_toutiao"
    assert bound.hitl_chat_id == "oc_toutiao"
    assert store.resolve_by_chat("oc_toutiao").id == "toutiao"

    # 同一 chat_id 不能绑两个部门
    with pytest.raises(ValueError):
        store.bind_chat("douyin", "oc_toutiao")

    created = store.create(
        DepartmentCreate(id="custom_dept", name="自定义部", member_employee_ids=["strategy"])
    )
    assert created.id == "custom_dept"
    store.delete("custom_dept")
    assert store.get("custom_dept") is None


def test_department_resolve_by_chat_default(data_dir):
    from matrixsolo.admin.departments import get_department_store
    from matrixsolo.feishu.chat import resolve_department_for_chat

    get_department_store().bind_chat("toutiao", "oc_toutiao")
    dept = resolve_department_for_chat("oc_toutiao")
    assert dept["id"] == "toutiao"
    assert "editor" not in dept["members"]
    default = resolve_department_for_chat("oc_default")
    assert default["id"] == "default"
    assert resolve_department_for_chat("oc_unknown") is None


def test_department_skips_editor_in_graph(data_dir):
    from matrixsolo.models import WorkflowState
    from matrixsolo.orchestration.graph import _department_skips_editor

    toutiao = WorkflowState(department_id="toutiao")
    assert _department_skips_editor(toutiao) is True
    douyin = WorkflowState(department_id="douyin")
    assert _department_skips_editor(douyin) is False
    default = WorkflowState(department_id="default")
    assert _department_skips_editor(default) is False


def test_department_member_functions_resolves_custom(data_dir):
    from matrixsolo.admin.employees import EmployeeCreate, get_employee_store
    from matrixsolo.orchestration.huddle import _member_functions

    get_employee_store().create(
        EmployeeCreate(id="visual_b", title="视觉B", function="visual", app_id="a", app_secret="s")
    )
    functions = _member_functions(["strategy", "visual_b"])
    assert "strategy" in functions
    assert "visual" in functions
