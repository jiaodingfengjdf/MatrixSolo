from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from matrixsolo.admin.mcp_runtime import RoleMcpRuntime
from matrixsolo.admin.models import (
    AgentProfile,
    AgentProfilePatch,
    LLM_PROVIDER_CATALOG,
    McpServerCreate,
    McpServerUpdate,
    PromptSkillCreate,
    PromptSkillUpdate,
)
from matrixsolo.admin.store import get_profile_store

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
    from matrixsolo.skills.package import SkillInstallError, install_skill_package, parse_skill_bytes

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
    return {
        "hitl_chat_id": s.feishu_hitl_chat_id,
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
