from __future__ import annotations

import logging
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from matrixsolo.admin.mcp_runtime import enrich_with_mcp_context
from matrixsolo.agents import (
    OperationsAgent,
    PostProductionAgent,
    ScriptwritingAgent,
    StrategyAgent,
    VisualAgent,
)
from matrixsolo.feishu.client import FeishuClient
from matrixsolo.feishu.hitl import HitlCards
from matrixsolo.models import HitlAction, WorkflowState, WorkflowStatus
from matrixsolo.orchestration.store import WorkflowStore

logger = logging.getLogger(__name__)


class GraphState(TypedDict, total=False):
    workflow: dict[str, Any]
    entry: str
    hitl_action: str
    hitl_payload: dict[str, Any]


def _load(state: GraphState) -> WorkflowState:
    return WorkflowState.model_validate(state["workflow"])


def _dump(wf: WorkflowState) -> dict[str, Any]:
    return wf.model_dump(mode="json")


def _department_skips_editor(wf: WorkflowState) -> bool:
    """部门成员不含 editor 职能 → 跳过真实剪辑渲染（图文 copy_pack 终审）."""
    if not wf.department_id or wf.department_id == "default":
        return False
    from matrixsolo.admin.departments import get_department_store

    department = get_department_store().get(wf.department_id)
    if not department:
        return False
    functions: set[str] = set()
    for employee_id in department.member_employee_ids or []:
        if employee_id in {"strategy", "script", "visual", "editor", "ops"}:
            functions.add(employee_id)
            continue
        from matrixsolo.admin.employees import get_employee_store

        employee = get_employee_store().get(employee_id)
        functions.add((employee.function if employee else employee_id) or employee_id)
    return "editor" not in functions


class ProductionOrchestrator:
    """LangGraph DAG：strategy → HITL1 → script → HITL2 → visual/audio/render → HITL3 → ops.

    飞书 HITL 为外部中断点：图执行到审批节点后结束；resume_hitl 从对应 entry 继续。
    """

    def __init__(self) -> None:
        self.store = WorkflowStore()
        self.strategy = StrategyAgent()
        self.scriptwriter = ScriptwritingAgent()
        self.visual = VisualAgent()
        self.post = PostProductionAgent()
        self.ops = OperationsAgent()
        self.feishu = FeishuClient()
        self.hitl = HitlCards(self.feishu)
        self._graph = self._build_graph()

    def _build_graph(self):
        g = StateGraph(GraphState)

        async def strategy_node(state: GraphState) -> GraphState:
            wf = _load(state)
            wf.status = WorkflowStatus.STRATEGY
            wf.log("LangGraph → strategy")
            mcp_ctx = await enrich_with_mcp_context("strategy")
            if mcp_ctx:
                wf.log(mcp_ctx[:200])
            wf = await self.strategy.propose_topics(wf)
            return {**state, "workflow": _dump(wf)}

        async def topic_hitl_node(state: GraphState) -> GraphState:
            wf = _load(state)
            wf.status = WorkflowStatus.AWAITING_TOPIC_APPROVAL
            msg_id = await self.hitl.send_topic_card(wf)
            if msg_id:
                wf.feishu_message_ids["topic"] = msg_id
            self.store.save(wf)
            return {**state, "workflow": _dump(wf)}

        async def apply_topic_decision(state: GraphState) -> GraphState:
            wf = _load(state)
            action = HitlAction(state.get("hitl_action") or "pass")
            payload = state.get("hitl_payload") or {}
            wf.hitl_topic_action = action
            if action == HitlAction.CUSTOM:
                wf.topic_custom_note = payload.get("note") or payload.get("text") or ""
            if action == HitlAction.REROLL:
                wf.topic_custom_note = payload.get("note") or wf.topic_custom_note
            if action == HitlAction.PASS:
                idx = int(payload.get("index", 0))
                if not wf.topics:
                    raise ValueError("no topics to approve")
                wf.selected_topic = wf.topics[min(idx, len(wf.topics) - 1)]
                wf.log(f"HITL1 通过选题：{wf.selected_topic.film_name}")
            elif action not in (HitlAction.REROLL, HitlAction.CUSTOM):
                wf.status = WorkflowStatus.CANCELLED
            return {**state, "workflow": _dump(wf)}

        async def script_node(state: GraphState) -> GraphState:
            wf = _load(state)
            if wf.status == WorkflowStatus.CANCELLED:
                return {**state, "workflow": _dump(wf)}
            wf.status = WorkflowStatus.SCRIPTING
            wf.log("LangGraph → script")
            mcp_ctx = await enrich_with_mcp_context("script")
            if mcp_ctx:
                wf.log(mcp_ctx[:200])
            wf = await self.scriptwriter.write(wf)
            if wf.status == WorkflowStatus.BLOCKED:
                await self.hitl.send_alert_card(wf)
                self.store.save(wf)
            return {**state, "workflow": _dump(wf)}

        async def script_hitl_node(state: GraphState) -> GraphState:
            wf = _load(state)
            if wf.status in (WorkflowStatus.BLOCKED, WorkflowStatus.CANCELLED):
                self.store.save(wf)
                return {**state, "workflow": _dump(wf)}
            wf.status = WorkflowStatus.AWAITING_SCRIPT_APPROVAL
            msg_id = await self.hitl.send_script_card(wf)
            if msg_id:
                wf.feishu_message_ids["script"] = msg_id
            self.store.save(wf)
            return {**state, "workflow": _dump(wf)}

        async def apply_script_decision(state: GraphState) -> GraphState:
            wf = _load(state)
            action = HitlAction(state.get("hitl_action") or "pass")
            payload = state.get("hitl_payload") or {}
            wf.hitl_script_action = action
            if not wf.script:
                raise ValueError("script missing")
            if action == HitlAction.REJECT:
                note = payload.get("note") or payload.get("text")
                if note:
                    wf.topic_custom_note = f"脚本修正要求: {note}"
            elif action == HitlAction.SELECT_TITLE:
                idx = int(payload.get("title_index", 0))
                wf.script.selected_title = wf.script.titles[min(idx, len(wf.script.titles) - 1)]
            elif action == HitlAction.PASS:
                wf.script.selected_title = wf.script.selected_title or wf.script.titles[0]
                wf.log(f"HITL2 通过文案，主推标题：{wf.script.selected_title}")
            else:
                wf.status = WorkflowStatus.CANCELLED
            return {**state, "workflow": _dump(wf)}

        async def produce_node(state: GraphState) -> GraphState:
            wf = _load(state)
            if wf.status == WorkflowStatus.CANCELLED:
                return {**state, "workflow": _dump(wf)}
            wf.status = WorkflowStatus.PRODUCING
            wf.log("LangGraph → visual + audio")
            mcp_ctx = await enrich_with_mcp_context("visual")
            if mcp_ctx:
                wf.log(mcp_ctx[:200])
            wf = await self.visual.generate_covers(wf)
            await self.hitl.send_cover_notice(wf)
            editor_mcp = await enrich_with_mcp_context("editor")
            if editor_mcp:
                wf.log(editor_mcp[:200])
            wf = await self.post.synthesize_audio(wf)
            return {**state, "workflow": _dump(wf)}

        async def render_node(state: GraphState) -> GraphState:
            wf = _load(state)
            wf.status = WorkflowStatus.RENDERING
            wf.log("LangGraph → render")
            # 图文模板（无 editor 成员）跳过真实剪辑渲染，产出 copy_pack 供终审
            if _department_skips_editor(wf):
                from matrixsolo.models import RenderResult

                title = (
                    (wf.script.selected_title if wf.script else "")
                    or (wf.selected_topic.film_name if wf.selected_topic else "")
                    or ""
                )
                wf.render = RenderResult(
                    preview_path=f"copy_pack://{wf.department_id}/{title}",
                    compliance_score=1.0,
                    compliance_report={"mode": "copy_pack", "department_id": wf.department_id},
                )
                wf.log("图文模板：跳过剪辑渲染，产出 copy_pack 终审")
                self.store.save(wf)
                return {**state, "workflow": _dump(wf)}
            wf = await self.post.render_via_mcp(wf)
            return {**state, "workflow": _dump(wf)}

        async def final_hitl_node(state: GraphState) -> GraphState:
            wf = _load(state)
            wf.status = WorkflowStatus.AWAITING_FINAL_APPROVAL
            msg_id = await self.hitl.send_final_card(wf)
            if msg_id:
                wf.feishu_message_ids["final"] = msg_id
            self.store.save(wf)
            return {**state, "workflow": _dump(wf)}

        async def apply_final_decision(state: GraphState) -> GraphState:
            wf = _load(state)
            action = HitlAction(state.get("hitl_action") or "schedule")
            wf.hitl_final_action = action
            if action == HitlAction.REEDIT:
                wf.log("HITL3 要求微调重剪")
            elif action not in (HitlAction.PUBLISH_NOW, HitlAction.SCHEDULE, HitlAction.PASS):
                wf.status = WorkflowStatus.CANCELLED
            return {**state, "workflow": _dump(wf)}

        async def distribute_node(state: GraphState) -> GraphState:
            wf = _load(state)
            action = HitlAction(state.get("hitl_action") or "schedule")
            if wf.status == WorkflowStatus.CANCELLED:
                self.store.save(wf)
                return {**state, "workflow": _dump(wf)}
            wf.status = WorkflowStatus.DISTRIBUTING
            wf.log("LangGraph → ops")
            mcp_ctx = await enrich_with_mcp_context("ops")
            if mcp_ctx:
                wf.log(mcp_ctx[:200])
            wf = await self.ops.package_and_schedule(wf)
            if action == HitlAction.PUBLISH_NOW:
                for pkg in wf.distributions:
                    pkg.status = "publishing_now"
                wf.log("运营 Agent：立即全网发布")
            else:
                wf.log("运营 Agent：加入排期队列")
            await self.hitl.send_distribution_notice(wf)
            await self.feishu.upsert_task_record(wf)
            wf.status = WorkflowStatus.COMPLETED
            wf.log("工作流完成")
            self.store.save(wf)
            from matrixsolo.admin.work_logs import record_work_log

            await record_work_log(
                project=(wf.selected_topic.film_name if wf.selected_topic else "") or "工作流",
                work_type="workflow",
                status="done",
                summary=f"生产 DAG 完成：{wf.trigger} / {wf.content_form.value}",
                workflow_id=wf.workflow_id,
                department_id=wf.department_id,
                department_name=wf.department_name,
                stage="distribute",
                employee_id="ops",
                employee_title="运营",
            )
            return {**state, "workflow": _dump(wf)}

        def route_start(state: GraphState) -> str:
            return state.get("entry") or "start"

        g.add_node("strategy", strategy_node)
        g.add_node("topic_hitl", topic_hitl_node)
        g.add_node("apply_topic", apply_topic_decision)
        g.add_node("script", script_node)
        g.add_node("script_hitl", script_hitl_node)
        g.add_node("apply_script", apply_script_decision)
        g.add_node("produce", produce_node)
        g.add_node("render", render_node)
        g.add_node("final_hitl", final_hitl_node)
        g.add_node("apply_final", apply_final_decision)
        g.add_node("distribute", distribute_node)

        g.add_conditional_edges(
            START,
            route_start,
            {
                "start": "strategy",
                "topic_reroll": "strategy",
                "topic_custom": "strategy",
                "topic_pass": "apply_topic",
                "script_reject": "apply_script",
                "script_pass": "apply_script",
                "final_reedit": "apply_final",
                "final_pass": "apply_final",
            },
        )
        g.add_edge("strategy", "topic_hitl")
        g.add_edge("topic_hitl", END)

        def after_topic(state: GraphState) -> str:
            wf = _load(state)
            action = HitlAction(state.get("hitl_action") or "pass")
            if wf.status == WorkflowStatus.CANCELLED:
                return "end"
            if action in (HitlAction.REROLL, HitlAction.CUSTOM):
                return "strategy"
            return "script"

        g.add_conditional_edges(
            "apply_topic",
            after_topic,
            {"strategy": "strategy", "script": "script", "end": END},
        )
        g.add_edge("script", "script_hitl")
        g.add_edge("script_hitl", END)

        def after_script(state: GraphState) -> str:
            wf = _load(state)
            action = HitlAction(state.get("hitl_action") or "pass")
            if wf.status == WorkflowStatus.CANCELLED:
                return "end"
            if action == HitlAction.REJECT:
                return "script"
            return "produce"

        g.add_conditional_edges(
            "apply_script",
            after_script,
            {"script": "script", "produce": "produce", "end": END},
        )
        g.add_edge("produce", "render")
        g.add_edge("render", "final_hitl")
        g.add_edge("final_hitl", END)

        def after_final(state: GraphState) -> str:
            wf = _load(state)
            action = HitlAction(state.get("hitl_action") or "schedule")
            if wf.status == WorkflowStatus.CANCELLED:
                return "end"
            if action == HitlAction.REEDIT:
                return "render"
            return "distribute"

        g.add_conditional_edges(
            "apply_final",
            after_final,
            {"render": "render", "distribute": "distribute", "end": END},
        )
        g.add_edge("distribute", END)
        return g.compile()

    async def _ainvoke(self, payload: GraphState) -> WorkflowState:
        result = await self._graph.ainvoke(payload)
        wf = WorkflowState.model_validate(result["workflow"])
        self.store.save(wf)
        return wf

    async def start(
        self,
        *,
        trigger: str = "manual",
        content_form: str | None = None,
        audience_profile: str | None = None,
        custom_note: str | None = None,
        department_id: str | None = None,
    ) -> WorkflowState:
        state = WorkflowState(trigger=trigger)
        if department_id:
            from matrixsolo.admin.departments import get_department_store

            department = get_department_store().get(department_id)
            if department:
                state.department_id = department.id
                state.department_name = department.name
                state.hitl_chat_id = department.target_chat_id()
        if audience_profile:
            state.audience_profile = audience_profile
        if content_form:
            from matrixsolo.models import ContentForm

            try:
                state.content_form = ContentForm(content_form)
            except ValueError:
                pass
        if custom_note:
            state.topic_custom_note = custom_note
        state.log("工作流启动 (LangGraph)")
        self.store.save(state)
        return await self._ainvoke({"workflow": _dump(state), "entry": "start"})

    async def resume_hitl(
        self,
        workflow_id: str,
        stage: Literal["topic", "script", "final"],
        action: HitlAction | str,
        payload: dict[str, Any] | None = None,
    ) -> WorkflowState:
        state = self.store.get(workflow_id)
        if not state:
            raise KeyError(f"workflow not found: {workflow_id}")
        action_enum = action if isinstance(action, HitlAction) else HitlAction(action)
        payload = payload or {}

        entry_map = {
            ("topic", HitlAction.PASS): "topic_pass",
            ("topic", HitlAction.REROLL): "topic_reroll",
            ("topic", HitlAction.CUSTOM): "topic_custom",
            ("script", HitlAction.PASS): "script_pass",
            ("script", HitlAction.SELECT_TITLE): "script_pass",
            ("script", HitlAction.REJECT): "script_reject",
            ("final", HitlAction.PUBLISH_NOW): "final_pass",
            ("final", HitlAction.SCHEDULE): "final_pass",
            ("final", HitlAction.PASS): "final_pass",
            ("final", HitlAction.REEDIT): "final_reedit",
        }
        entry = entry_map.get((stage, action_enum))
        if not entry:
            if stage == "topic":
                state.status = WorkflowStatus.CANCELLED
            elif stage == "script":
                state.status = WorkflowStatus.CANCELLED
            else:
                state.status = WorkflowStatus.CANCELLED
            self.store.save(state)
            await self._record_hitl_log(workflow_id, stage, action_enum, state, {"action": "cancel"})
            return state

        # topic_reroll/custom go straight to strategy without apply_topic
        if entry in ("topic_reroll", "topic_custom"):
            state.hitl_topic_action = action_enum
            if entry == "topic_custom":
                state.topic_custom_note = payload.get("note") or payload.get("text") or ""
            else:
                state.topic_custom_note = payload.get("note") or state.topic_custom_note

        new_state = await self._ainvoke(
            {
                "workflow": _dump(state),
                "entry": entry,
                "hitl_action": action_enum.value,
                "hitl_payload": payload,
            }
        )
        await self._record_hitl_log(workflow_id, stage, action_enum, new_state, payload)
        return new_state

    async def _record_hitl_log(
        self,
        workflow_id: str,
        stage: str,
        action: HitlAction,
        state: WorkflowState,
        payload: dict[str, Any],
    ) -> None:
        from matrixsolo.admin.work_logs import record_work_log

        project = (state.selected_topic.film_name if state.selected_topic else "") or "工作流"
        await record_work_log(
            project=project,
            work_type="hitl",
            status="blocked" if state.status.value.startswith("awaiting_") else "done",
            summary=f"HITL-{stage} {action.value}",
            workflow_id=workflow_id,
            department_id=state.department_id,
            department_name=state.department_name,
            stage=stage,
            employee_id="strategy",
            employee_title="总编",
            extra=payload,
        )

    async def auto_approve_demo(self, workflow_id: str) -> WorkflowState:
        state = await self.resume_hitl(workflow_id, "topic", HitlAction.PASS, {"index": 0})
        if state.status == WorkflowStatus.BLOCKED:
            return state
        state = await self.resume_hitl(workflow_id, "script", HitlAction.PASS, {"title_index": 0})
        if state.status == WorkflowStatus.AWAITING_FINAL_APPROVAL:
            state = await self.resume_hitl(workflow_id, "final", HitlAction.SCHEDULE, {})
        return state
