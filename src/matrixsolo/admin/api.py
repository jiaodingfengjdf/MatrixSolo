from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

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
from matrixsolo.admin.store import get_profile_store
from matrixsolo.admin.work_logs import WorkLogCreate, get_work_log_store, record_work_log

router = APIRouter(prefix="/api/admin", tags=["admin"])

_NO_STORE = {"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"}


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
                "role": a.role.value,
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
