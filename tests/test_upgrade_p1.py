from __future__ import annotations

import asyncio
import sys

import pytest


def _reset_singletons() -> None:
    import matrixsolo.admin.employees as emp
    import matrixsolo.admin.model_center as mc
    import matrixsolo.admin.prompt_os as po
    import matrixsolo.admin.store as st
    import matrixsolo.admin.tool_audit as ta
    import matrixsolo.admin.work_logs as wl

    emp._store = None
    mc._store = None
    po._studio = None
    po._versions = None
    st._store = None
    ta._store = None
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


def test_employee_registry_seed_and_custom(data_dir):
    from matrixsolo.admin.employees import EmployeeCreate, get_employee_store
    from matrixsolo.feishu.staff import employee_title_map, resolve_staff_apps

    store = get_employee_store()
    ids = {e.id for e in store.list()}
    assert {"strategy", "script", "visual", "editor", "ops"} <= ids

    created = store.create(
        EmployeeCreate(
            id="headline_editor",
            title="头条编辑",
            function="script",
            app_id="cli_abc",
            app_secret="secret-1234567890",
        )
    )
    assert created.dump_admin()["app_secret_masked"].endswith("7890")
    assert "app_secret" not in created.dump_admin()

    apps = resolve_staff_apps()
    assert "headline_editor" in apps
    assert apps["headline_editor"].title == "头条编辑"
    assert employee_title_map()["头条编辑"] == "headline_editor"

    disabled = store.set_enabled("headline_editor", False)
    assert disabled.enabled is False
    assert "headline_editor" not in resolve_staff_apps()


def test_profile_lazy_create_and_polish_skeleton(data_dir):
    from matrixsolo.admin.employees import EmployeeCreate, EmployeePolishRequest, get_employee_store
    from matrixsolo.admin.polish import polish_draft
    from matrixsolo.admin.store import get_profile_store

    get_employee_store().create(
        EmployeeCreate(id="editor2", title="阿贰", function="editor", app_id="a", app_secret="s")
    )
    profile = get_profile_store().get_or_create("editor2")
    assert profile.role == "editor2"
    assert profile.identity and profile.capability_boundary and "越界话术" in profile.capability_boundary

    # 无 Key 时润色回退骨架，不 500
    employee = get_employee_store().get("editor2")
    result = asyncio.run(
        polish_draft(employee, EmployeePolishRequest(one_liner="负责剪辑", department="视频抖音部"))
    )
    assert set(result["draft"]) == {
        "identity",
        "personality",
        "craft",
        "work_style",
        "memory",
        "capability_boundary",
        "system_prompt",
    }
    assert all(result["draft"][k] for k in result["draft"])


def test_tool_audit_from_runtime(data_dir):
    from matrixsolo.admin.store import get_profile_store
    from matrixsolo.admin.tool_audit import get_tool_audit_store
    from matrixsolo.skills.runtime import SkillRuntime

    profile = get_profile_store().get("strategy")
    result = asyncio.run(SkillRuntime().run("hot_radar", profile))
    assert result["ok"] is True
    rows = get_tool_audit_store().list(employee_id="strategy", kind="runtime")
    assert any(r["tool"] == "hot_radar" and r["ok"] for r in rows)


def test_mcp_stdio_list_and_call(data_dir):
    from matrixsolo.admin.mcp_runtime import RoleMcpRuntime
    from matrixsolo.admin.store import get_profile_store

    script = (
        "import sys,json\n"
        "for line in sys.stdin:\n"
        "    line=line.strip()\n"
        "    if not line: continue\n"
        "    m=json.loads(line)\n"
        "    if m.get('method')=='initialize':\n"
        "        print(json.dumps({'jsonrpc':'2.0','id':m['id'],'result':{'protocolVersion':'2024-11-05'}}),flush=True)\n"
        "    elif m.get('method')=='tools/list':\n"
        "        print(json.dumps({'jsonrpc':'2.0','id':m['id'],'result':{'tools':[{'name':'echo','description':'echo'}]}}),flush=True)\n"
        "    elif m.get('method')=='tools/call':\n"
        "        print(json.dumps({'jsonrpc':'2.0','id':m['id'],'result':{'content':[{'type':'text','text':'pong'}]}}),flush=True)\n"
    )
    from matrixsolo.admin.models import McpServerCreate

    get_profile_store().add_mcp(
        "strategy",
        McpServerCreate(
            name="mock-stdio",
            transport="stdio",
            command=sys.executable,
            args=["-c", script],
            enabled=True,
        ),
    )
    runtime = RoleMcpRuntime("strategy")
    tools = asyncio.run(runtime.list_tools())
    assert any(t.get("name") == "echo" for t in tools)
    server = next(s for s in runtime.servers if s.name == "mock-stdio")
    called = asyncio.run(runtime.call_tool(server.id, "echo", {"msg": "hi"}))
    assert called["ok"] is True
    assert "pong" in str(called.get("result"))
