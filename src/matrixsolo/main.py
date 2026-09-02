from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from matrixsolo import __version__
from matrixsolo.admin import admin_router
from matrixsolo.analytics import ReviewEngine
from matrixsolo.config import get_settings
from matrixsolo.feishu.chat import (
    extract_card_value,
    get_chat_worker,
    handle_card_action,
    handle_im_message,
)
from matrixsolo.feishu.staff import staff_status
from matrixsolo.models import HitlAction
from matrixsolo.orchestration import ProductionOrchestrator, WorkflowStore
from matrixsolo.scheduler import MatrixScheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("matrixsolo")

orchestrator = ProductionOrchestrator()
store = WorkflowStore()
scheduler = MatrixScheduler()
reviewer = ReviewEngine()


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()
    scheduler.start()
    get_chat_worker().start()
    logger.info("MatrixSolo v%s ready on %s:%s", __version__, settings.host, settings.port)
    yield
    get_chat_worker().shutdown()
    scheduler.shutdown()


app = FastAPI(
    title="MatrixSolo",
    description="一人影视自媒体多 Agent 协作中台",
    version=__version__,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(admin_router)


class StartRequest(BaseModel):
    trigger: str = "manual"
    content_form: str | None = Field(default=None, description="逐帧解说/混剪盘点/影评漫谈/幕后花絮")
    audience_profile: str | None = None
    custom_note: str | None = None
    department_id: str | None = None
    auto_demo: bool = Field(default=False, description="本地演示：自动通过三道 HITL")


class HitlRequest(BaseModel):
    workflow_id: str
    stage: Literal["topic", "script", "final"]
    action: HitlAction
    payload: dict[str, Any] = Field(default_factory=dict)


class MetricsRequest(BaseModel):
    retention_5s: float = 0.0
    completion_rate: float = 0.0
    ctr: float = 0.0
    follow_rate: float = 0.0


@app.get("/health")
async def health() -> dict[str, Any]:
    s = get_settings()
    return {
        "status": "ok",
        "version": __version__,
        "feishu_configured": any(
            v["configured"] for v in staff_status(s).values()
        ),
        "feishu_staff": staff_status(s),
        "llm_default": s.llm_default_provider,
    }


@app.get("/api/feishu/staff/verify")
async def verify_feishu_staff() -> dict[str, Any]:
    """验证五岗 AI 员工 App 凭证能否换取 tenant_access_token."""
    return await orchestrator.feishu.verify_all_tokens()


@app.post("/api/workflows/start")
async def start_workflow(body: StartRequest) -> dict[str, Any]:
    state = await orchestrator.start(
        trigger=body.trigger,
        content_form=body.content_form,
        audience_profile=body.audience_profile,
        custom_note=body.custom_note,
        department_id=body.department_id,
    )
    if body.auto_demo:
        state = await orchestrator.auto_approve_demo(state.workflow_id)
    return state.model_dump(mode="json")


@app.get("/api/workflows")
async def list_workflows(limit: int = 50) -> dict[str, Any]:
    return {"items": store.list(limit=limit)}


@app.get("/api/workflows/{workflow_id}")
async def get_workflow(workflow_id: str) -> dict[str, Any]:
    state = store.get(workflow_id)
    if not state:
        raise HTTPException(404, "workflow not found")
    return state.model_dump(mode="json")


@app.post("/api/hitl/resume")
async def resume_hitl(body: HitlRequest) -> dict[str, Any]:
    try:
        state = await orchestrator.resume_hitl(
            body.workflow_id, body.stage, body.action, body.payload
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return state.model_dump(mode="json")


@app.post("/api/feishu/event")
@app.post("/api/feishu/event/{role}")
async def feishu_event(request: Request, role: str | None = None) -> dict[str, Any]:
    """飞书事件：url_verification + IM 消息回复 + 卡片回传."""
    settings = get_settings()
    payload = await request.json()
    if payload.get("type") == "url_verification":
        if settings.feishu_verification_token and payload.get("token") != settings.feishu_verification_token:
            raise HTTPException(403, "invalid verification token")
        return {"challenge": payload.get("challenge")}

    # 新版卡片回传：必须立刻 HTTP 200 + toast，工作流后台跑，否则飞书报 200671
    header = payload.get("header") or {}
    event_type = header.get("event_type") or payload.get("event", {}).get("type") or ""
    card_value = extract_card_value(payload)
    if event_type == "card.action.trigger" or (
        card_value.get("workflow_id") and card_value.get("stage") and card_value.get("action")
    ):
        asyncio.create_task(
            handle_card_action({"kind": "card_action", "value": card_value})
        )
        return {"toast": {"type": "info", "content": "收到，工作室接着干。"}}

    # 新版事件包装
    if event_type == "im.message.receive_v1" or (
        payload.get("event") and (payload.get("event") or {}).get("message")
    ):
        if role and not (payload.get("header") or {}).get("app_id"):
            # 路径带岗位时，用岗位 app 映射
            from matrixsolo.feishu.staff import AgentRole, resolve_staff_apps

            try:
                r = AgentRole(role)
                app = resolve_staff_apps().get(r)
                if app:
                    payload.setdefault("header", {})["app_id"] = app.app_id
            except ValueError:
                pass
        return await handle_im_message(payload)

    return {"code": 0}


@app.post("/api/analytics/review")
async def analytics_review(body: MetricsRequest) -> dict[str, Any]:
    metrics = body.model_dump()
    insights = reviewer.analyze(metrics)
    return {
        "report_markdown": reviewer.daily_report(metrics),
        "insights": [i.__dict__ for i in insights],
    }


def run() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "matrixsolo.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    run()
