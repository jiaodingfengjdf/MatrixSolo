from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from matrixsolo.admin.employees import (
    EmployeeCreate,
    EmployeePolishRequest,
    EmployeeUpdate,
    get_employee_store,
)
from matrixsolo.admin.mcp_runtime import RoleMcpRuntime
from matrixsolo.admin.model_center import (
    ModelProviderCreate,
    ModelProviderUpdate,
    ModelSlotCreate,
    ModelSlotUpdate,
    get_model_store,
)
from matrixsolo.admin.models import (
    LLM_PROVIDER_CATALOG,
    AgentProfile,
    AgentProfilePatch,
    McpServerCreate,
    McpServerUpdate,
    PromptSkillCreate,
    PromptSkillUpdate,
)
from matrixsolo.admin.polish import PERSONA_FIELDS, polish_draft
from matrixsolo.admin.store import get_profile_store
from matrixsolo.admin.tool_audit import get_tool_audit_store
from matrixsolo.admin.work_logs import WorkLogCreate, get_work_log_store, record_work_log

router = APIRouter(prefix="/api/admin", tags=["admin"])
logger = logging.getLogger(__name__)

_NO_STORE = {"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"}


def _reload_ws_worker() -> bool:
    """入职/停用后热重载飞书长连接；失败不阻断主流程."""
    try:
        from matrixsolo.feishu.chat import get_chat_worker

        get_chat_worker().reload_apps()
        return True
    except Exception:  # noqa: BLE001
        logger.debug("ws reload skipped")
        return False


def _profile_ok(profile: AgentProfile) -> JSONResponse:
    return JSONResponse(content=profile.dump_admin(), headers=_NO_STORE)


def _profiles_ok(items: list[AgentProfile], key: str = "items") -> JSONResponse:
    return JSONResponse(
        content={key: [p.dump_admin() for p in items]},
        headers=_NO_STORE,
    )


class McpCallRequest(BaseModel):
    server_id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class SkillInstallRequest(BaseModel):
    url: str


class PromptStudioUpdate(BaseModel):
    studio_voice: str = ""
    colleagues: str = ""


class PromptRollbackRequest(BaseModel):
    version: int


class PolishApplyRequest(BaseModel):
    draft: dict[str, str]


@router.get("/agents")
async def list_agents() -> JSONResponse:
    return _profiles_ok(get_profile_store().list())


@router.get("/agents/{role}")
async def get_agent(role: str) -> JSONResponse:
    try:
        return _profile_ok(get_profile_store().get(role))
    except KeyError as exc:
        raise HTTPException(404, f"agent role not found: {role}") from exc


@router.put("/agents/{role}")
async def update_agent(role: str, body: AgentProfilePatch) -> JSONResponse:
    try:
        return _profile_ok(get_profile_store().update(role, body))
    except KeyError as exc:
        raise HTTPException(404, f"agent role not found: {role}") from exc


@router.get("/tools/catalog")
async def tool_catalog() -> dict[str, Any]:
    return {"items": get_profile_store().tool_catalog()}


@router.get("/llm/providers")
async def llm_providers() -> dict[str, Any]:
    return {"items": LLM_PROVIDER_CATALOG}


# --------------------------------------------------------------------------- #
# 模型中心（PRD 模块 1 / 9）
# --------------------------------------------------------------------------- #
@router.get("/model-providers")
async def list_model_providers() -> dict[str, Any]:
    from matrixsolo.admin.model_center import get_model_store

    store = get_model_store()
    return {
        "default_provider_id": store.default_provider_id(),
        "items": [p.dump_admin() for p in store.list_providers()],
    }


@router.post("/model-providers")
async def create_model_provider(body: ModelProviderCreate) -> dict[str, Any]:
    try:
        provider = get_model_store().create_provider(body)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return provider.dump_admin()


@router.put("/model-providers/{provider_id}")
async def update_model_provider(
    provider_id: str, body: ModelProviderUpdate
) -> dict[str, Any]:
    try:
        provider = get_model_store().update_provider(provider_id, body)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return provider.dump_admin()


@router.delete("/model-providers/{provider_id}")
async def delete_model_provider(provider_id: str) -> dict[str, Any]:
    try:
        get_model_store().delete_provider(provider_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True}


@router.post("/model-providers/{provider_id}/probe")
async def probe_model_provider(
    provider_id: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    body = body or {}
    from matrixsolo.gateway import get_gateway

    result = await get_gateway().probe(
        provider_id,
        model_id=body.get("model_id"),
        base_url=body.get("base_url"),
    )
    return result


@router.get("/model-slots")
async def list_model_slots() -> dict[str, Any]:
    store = get_model_store()
    providers = {p.id: p for p in store.list_providers()}
    items = []
    for slot in store.list_slots():
        item = slot.model_dump(mode="json")
        provider = providers.get(slot.provider_id)
        item["provider_name"] = provider.name if provider else ""
        item["provider_base_url"] = provider.base_url if provider else ""
        item["capability"] = [c.value for c in slot.capability]
        items.append(item)
    return {"items": items}


@router.post("/model-slots")
async def create_model_slot(body: ModelSlotCreate) -> dict[str, Any]:
    try:
        slot = get_model_store().create_slot(body)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return slot.model_dump(mode="json")


@router.put("/model-slots/{slot_id}")
async def update_model_slot(slot_id: str, body: ModelSlotUpdate) -> dict[str, Any]:
    try:
        slot = get_model_store().update_slot(slot_id, body)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return slot.model_dump(mode="json")


@router.delete("/model-slots/{slot_id}")
async def delete_model_slot(slot_id: str) -> dict[str, Any]:
    try:
        get_model_store().delete_slot(slot_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"ok": True}


# --------------------------------------------------------------------------- #
# 员工入职 / 一键润色 / 工具审计（PRD 模块 8 / 2）
# --------------------------------------------------------------------------- #
@router.get("/employees")
async def list_employees() -> dict[str, Any]:
    return {"items": [e.dump_admin() for e in get_employee_store().list()]}


@router.post("/employees")
async def create_employee(body: EmployeeCreate) -> dict[str, Any]:
    try:
        employee = get_employee_store().create(body)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    # 入职即建人设（骨架）并热重载 WS，之后可一键润色上岗
    get_profile_store().get_or_create(employee.id)
    _reload_ws_worker()
    return employee.dump_admin()


@router.get("/employees/{employee_id}")
async def get_employee(employee_id: str) -> dict[str, Any]:
    employee = get_employee_store().get(employee_id)
    if not employee:
        raise HTTPException(404, f"employee not found: {employee_id}")
    profile = get_profile_store().get_or_create(employee_id)
    data = employee.dump_admin()
    data["profile"] = profile.dump_admin() if profile else None
    return data


@router.put("/employees/{employee_id}")
async def update_employee(employee_id: str, body: EmployeeUpdate) -> dict[str, Any]:
    try:
        employee = get_employee_store().update(employee_id, body)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return employee.dump_admin()


@router.post("/employees/{employee_id}/polish")
async def polish_employee(
    employee_id: str, body: EmployeePolishRequest
) -> dict[str, Any]:
    employee = get_employee_store().get(employee_id)
    if not employee:
        raise HTTPException(404, f"employee not found: {employee_id}")
    return await polish_draft(employee, body)


@router.post("/employees/{employee_id}/polish/apply")
async def apply_polish(
    employee_id: str, body: PolishApplyRequest
) -> JSONResponse:
    # 确认润色：把草稿写入人设并追加 source=polish 版本（可回滚）
    from matrixsolo.admin.models import AgentProfilePatch

    draft = {k: str(v) for k, v in body.draft.items() if k in PERSONA_FIELDS}
    try:
        profile = get_profile_store().update(
            employee_id,
            AgentProfilePatch(**draft),
            version_source="polish",
            version_note="一键润色确认",
        )
    except KeyError as exc:
        # 员工存在但 profile 未建（异常时序）→ 懒创建后重试
        if get_employee_store().get(employee_id) is None:
            raise HTTPException(404, str(exc)) from exc
        get_profile_store().get_or_create(employee_id)
        profile = get_profile_store().update(
            employee_id,
            AgentProfilePatch(**draft),
            version_source="polish",
            version_note="一键润色确认",
        )
    return _profile_ok(profile)


@router.post("/employees/{employee_id}/disable")
async def disable_employee(employee_id: str) -> dict[str, Any]:
    try:
        employee = get_employee_store().set_enabled(employee_id, False)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    _reload_ws_worker()
    return employee.dump_admin()


@router.post("/employees/{employee_id}/enable")
async def enable_employee(employee_id: str) -> dict[str, Any]:
    try:
        employee = get_employee_store().set_enabled(employee_id, True)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    _reload_ws_worker()
    return employee.dump_admin()


@router.post("/workers/reload")
async def reload_workers() -> dict[str, Any]:
    from matrixsolo.feishu.chat import get_chat_worker

    try:
        return get_chat_worker().reload_apps()
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@router.get("/tool-audit")
async def list_tool_audit(
    limit: int = 200,
    employee_id: str | None = None,
    kind: str | None = None,
    tool: str | None = None,
) -> dict[str, Any]:
    return {
        "items": get_tool_audit_store().list(
            limit=limit,
            employee_id=employee_id,
            kind=kind,
            tool=tool,
        )
    }


# --------------------------------------------------------------------------- #
# Prompt OS（PRD 模块 7）：L0 工作室 + 版本回滚
# --------------------------------------------------------------------------- #
@router.get("/prompt/studio")
async def get_prompt_studio() -> dict[str, Any]:
    from matrixsolo.admin.prompt_os import get_studio_prompt_store

    return get_studio_prompt_store().get().model_dump(mode="json")


@router.put("/prompt/studio")
async def update_prompt_studio(body: PromptStudioUpdate) -> dict[str, Any]:
    from matrixsolo.admin.prompt_os import get_studio_prompt_store

    prompt = get_studio_prompt_store().update(body.studio_voice, body.colleagues)
    return prompt.model_dump(mode="json")


@router.get("/agents/{role}/prompt/versions")
async def list_prompt_versions(role: str) -> dict[str, Any]:
    try:
        return {"items": get_profile_store().list_prompt_versions(role)}
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/agents/{role}/prompt/rollback")
async def rollback_prompt(role: str, body: PromptRollbackRequest) -> JSONResponse:
    try:
        return _profile_ok(get_profile_store().rollback_prompt(role, body.version))
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


# --------------------------------------------------------------------------- #
# 每日工作记录（PRD 模块 5）
# --------------------------------------------------------------------------- #
@router.get("/work-logs")
async def list_work_logs(
    limit: int = 200,
    date_from: str | None = None,
    date_to: str | None = None,
    department_id: str | None = None,
    employee_id: str | None = None,
    status: str | None = None,
    work_type: str | None = None,
) -> dict[str, Any]:
    rows = get_work_log_store().list(
        limit=limit,
        date_from=date_from,
        date_to=date_to,
        department_id=department_id,
        employee_id=employee_id,
        status=status,
        work_type=work_type,
    )
    return {"items": [r.model_dump(mode="json") for r in rows]}


@router.post("/work-logs")
async def create_work_log(body: WorkLogCreate) -> dict[str, Any]:
    payload = body
    log = await record_work_log(
        project=payload.project,
        work_type=payload.work_type,
        status=payload.status,
        summary=payload.summary,
        workflow_id=payload.workflow_id,
        chat_id=payload.chat_id,
        stage=payload.stage,
        employee_id=payload.employee_id,
        employee_title=payload.employee_title,
        department_id=payload.department_id,
        department_name=payload.department_name,
        artifact_url=payload.artifact_url,
        extra=payload.extra,
    )
    if not log:
        raise HTTPException(500, "work log record failed")
    return log.model_dump(mode="json")


@router.post("/agents/{role}/skills")
async def add_skill(role: str, body: PromptSkillCreate) -> dict[str, Any]:
    try:
        return _profile_ok(get_profile_store().add_skill(role, body))
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/agents/{role}/skills/install")
async def install_skill_url(role: str, body: SkillInstallRequest) -> JSONResponse:
    from matrixsolo.skills.package import SkillInstallError, install_skill_package, package_from_url

    url = (body.url or "").strip()
    if not url:
        raise HTTPException(400, "url required")
    try:
        pack = await package_from_url(url)
        skill = install_skill_package(role, pack, filename=url)
        return _profile_ok(get_profile_store().install_skill(role, skill))
    except KeyError as exc:
        raise HTTPException(404, f"agent role not found: {role}") from exc
    except SkillInstallError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/agents/{role}/skills/upload")
async def upload_skill(role: str, file: UploadFile = File(...)) -> JSONResponse:
    from matrixsolo.skills.package import (
        SkillInstallError,
        install_skill_package,
        parse_skill_bytes,
    )

    try:
        data = await file.read()
        pack = parse_skill_bytes(data, file.filename or "skill.md")
        pack.source = "upload"
        pack.origin = file.filename or ""
        skill = install_skill_package(role, pack, raw=data, filename=file.filename or "")
        return _profile_ok(get_profile_store().install_skill(role, skill))
    except KeyError as exc:
        raise HTTPException(404, f"agent role not found: {role}") from exc
    except SkillInstallError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.patch("/agents/{role}/skills/{skill_id}")
async def update_skill(role: str, skill_id: str, body: PromptSkillUpdate) -> dict[str, Any]:
    try:
        return _profile_ok(get_profile_store().update_skill(role, skill_id, body))
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.delete("/agents/{role}/skills/{skill_id}")
async def delete_skill(role: str, skill_id: str) -> dict[str, Any]:
    try:
        return _profile_ok(get_profile_store().delete_skill(role, skill_id))
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/agents/{role}/mcp")
async def add_mcp(role: str, body: McpServerCreate) -> dict[str, Any]:
    try:
        return _profile_ok(get_profile_store().add_mcp(role, body))
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.patch("/agents/{role}/mcp/{mcp_id}")
async def update_mcp(role: str, mcp_id: str, body: McpServerUpdate) -> dict[str, Any]:
    try:
        return _profile_ok(get_profile_store().update_mcp(role, mcp_id, body))
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.delete("/agents/{role}/mcp/{mcp_id}")
async def delete_mcp(role: str, mcp_id: str) -> dict[str, Any]:
    try:
        return _profile_ok(get_profile_store().delete_mcp(role, mcp_id))
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/agents/{role}/mcp/tools")
async def list_mcp_tools(role: str) -> dict[str, Any]:
    try:
        runtime = RoleMcpRuntime(role)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {
        "servers": [s.model_dump(mode="json") for s in runtime.servers],
        "tools": await runtime.list_tools(),
    }


@router.post("/agents/{role}/mcp/call")
async def call_mcp_tool(role: str, body: McpCallRequest) -> dict[str, Any]:
    try:
        runtime = RoleMcpRuntime(role)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return await runtime.call_tool(body.server_id, body.tool_name, body.arguments)


@router.post("/agents/reset")
async def reset_agents() -> dict[str, Any]:
    return _profiles_ok(get_profile_store().reset_defaults())


@router.get("/system/overview")
async def system_overview() -> dict[str, Any]:
    from matrixsolo.config import get_settings
    from matrixsolo.feishu.staff import staff_status

    s = get_settings()
    agents = get_profile_store().list()
    from matrixsolo.admin.work_logs import business_today
    from matrixsolo.orchestration.store import WorkflowStore

    today = business_today()
    work_log_store = get_work_log_store()
    today_logs = work_log_store.list(date_from=today, date_to=today, limit=1000)
    blocked_hitl = [
        w
        for w in WorkflowStore().list(limit=100)
        if w.get("status", "").startswith("awaiting_")
    ]
    return {
        "hitl_chat_id": s.feishu_hitl_chat_id,
        "today": today,
        "today_work_logs": len(today_logs),
        "work_logs_feishu_configured": bool(
            s.feishu_bitable_app_token and s.feishu_table_work_logs
        ),
        "work_logs": [r.model_dump(mode="json") for r in today_logs],
        "blocked_hitl": blocked_hitl,
        "feishu_staff": staff_status(s),
        "agents": [
            {
                "role": a.role,
                "title": a.title,
                "enabled": a.enabled,
                "llm": a.llm.model_dump(),
                "tools_enabled": [t.key for t in a.tools if t.enabled],
                "skills_count": len(a.skills),
                "mcp_count": len([m for m in a.mcp_servers if m.enabled]),
            }
            for a in agents
        ],
    }


@router.get("/studio/board")
async def studio_board(limit: int = 40) -> dict[str, Any]:
    from matrixsolo.admin.studio_memory import (
        load_studio_context,
        recent_calendar,
        recent_feishu_traces,
    )
    from matrixsolo.orchestration.store import WorkflowStore

    store = WorkflowStore()
    return {
        "huddle": load_studio_context(),
        "workflows": store.list(limit=limit),
        "calendar": recent_calendar(20),
        "feishu_trace": recent_feishu_traces(60),
    }
