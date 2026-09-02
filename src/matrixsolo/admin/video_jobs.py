from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import uuid4

from matrixsolo.admin.model_center import ModelCapability, get_model_store
from matrixsolo.admin.work_logs import record_work_log

logger = logging.getLogger(__name__)


def has_video_capability() -> bool:
    store = get_model_store()
    return any(
        slot.enabled and ModelCapability.VIDEO in slot.capability
        for slot in store.list_slots()
    )


class VideoJobManager:
    """视频生成异步任务：先写工作记录 started，后台失败/完成再更新，不阻塞卡片回调."""

    async def create(
        self,
        *,
        prompt: str,
        ref_images: list[str] | None = None,
        duration: float = 0.0,
        workflow_id: str = "",
        project: str = "",
        employee_id: str = "ops",
        employee_title: str = "运营",
        department_id: str = "default",
        department_name: str = "默认",
    ) -> dict[str, Any]:
        task_id = f"video-{uuid4().hex[:12]}"
        status = "started" if has_video_capability() else "failed"
        summary = (
            f"视频任务已创建 {task_id}"
            if status == "started"
            else "视频任务失败：未配置 video 能力槽位（P3 供应商待决策）"
        )
        await record_work_log(
            project=project or "视频生成",
            work_type="workflow",
            status=status,
            summary=summary,
            workflow_id=workflow_id,
            stage="video",
            employee_id=employee_id,
            employee_title=employee_title,
            department_id=department_id,
            department_name=department_name,
            extra={"task_id": task_id, "prompt": (prompt or "")[:400], "duration": duration},
        )
        if status == "started":
            asyncio.create_task(
                self._run(
                    task_id=task_id,
                    prompt=prompt,
                    workflow_id=workflow_id,
                    project=project,
                    employee_id=employee_id,
                    employee_title=employee_title,
                    department_id=department_id,
                    department_name=department_name,
                )
            )
        return {"task_id": task_id, "status": status}

    async def _run(self, **kwargs: Any) -> None:
        # 供应商接入点：真实 video provider 在此轮询/回写；P3 尚未定标，先统一失败可见
        await asyncio.sleep(2)
        await record_work_log(
            project=kwargs.get("project") or "视频生成",
            work_type="workflow",
            status="failed",
            summary="视频任务失败：provider 未实现（P3 待决策，已降级静帧+TTS）",
            workflow_id=kwargs.get("workflow_id") or "",
            stage="video",
            employee_id=kwargs.get("employee_id") or "ops",
            employee_title=kwargs.get("employee_title") or "运营",
            department_id=kwargs.get("department_id") or "default",
            department_name=kwargs.get("department_name") or "默认",
            extra={"task_id": kwargs.get("task_id"), "prompt": (kwargs.get("prompt") or "")[:400]},
        )


_manager: VideoJobManager | None = None


def get_video_job_manager() -> VideoJobManager:
    global _manager
    if _manager is None:
        _manager = VideoJobManager()
    return _manager
