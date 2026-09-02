from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from matrixsolo.config import Settings, get_settings
from matrixsolo.feishu.staff import StaffApp, employee_title, resolve_staff_apps
from matrixsolo.models import WorkflowState

logger = logging.getLogger(__name__)


class FeishuClient:
    """飞书 Open API：按 AI 员工岗位分别鉴权发消息 / 写多维表格."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._staff = resolve_staff_apps(self.settings)
        self._tokens: dict[str, tuple[str, float]] = {}

    def app_for(self, role: str) -> StaffApp:
        return self._staff[role]

    def configured(self, role: str | None = None) -> bool:
        if role is None:
            return any(a.app_id and a.app_secret for a in self._staff.values())
        app = self._staff[role]
        return bool(app.app_id and app.app_secret)

    async def get_tenant_access_token(self, role: str = "strategy") -> str | None:
        app = self._staff[role]
        if not (app.app_id and app.app_secret):
            return None
        cached = self._tokens.get(role)
        if cached and cached[1] > time.time() + 60:
            return cached[0]

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": app.app_id, "app_secret": app.app_secret},
            )
            data = resp.json()
            if data.get("code") != 0:
                logger.error("Feishu token error [%s/%s]: %s", str(role), app.title, data)
                return None
            token = data["tenant_access_token"]
            expire = float(data.get("expire", 7200))
            self._tokens[role] = (token, time.time() + expire)
            return token

    async def send_interactive(
        self,
        chat_id: str,
        card: dict[str, Any],
        *,
        role: str = "strategy",
    ) -> str | None:
        token = await self.get_tenant_access_token(role)
        staff = self.app_for(role)
        if not token:
            logger.info(
                "Feishu [%s] not configured; card dumped to logs only", staff.title
            )
            logger.info("CARD: %s", card.get("header", {}))
            return None
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://open.feishu.cn/open-apis/im/v1/messages",
                params={"receive_id_type": "chat_id"},
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "receive_id": chat_id,
                    "msg_type": "interactive",
                    "content": json.dumps(card, ensure_ascii=False),
                },
            )
            data = resp.json()
            if data.get("code") != 0:
                logger.error(
                    "Feishu send failed [%s/%s]: %s", str(role), staff.title, data
                )
                return None
            return (data.get("data") or {}).get("message_id")

    async def reply_text(
        self,
        message_id: str,
        text: str,
        *,
        role: str = "strategy",
    ) -> bool:
        token = await self.get_tenant_access_token(role)
        if not token:
            return False
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "msg_type": "text",
                    "content": json.dumps({"text": text}, ensure_ascii=False),
                },
            )
            data = resp.json()
            if data.get("code") != 0:
                logger.error("Feishu reply failed [%s]: %s", str(role), data)
                return False
            return True

    async def send_text(
        self,
        chat_id: str,
        text: str,
        *,
        role: str = "strategy",
    ) -> str | None:
        token = await self.get_tenant_access_token(role)
        if not token:
            return None
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://open.feishu.cn/open-apis/im/v1/messages",
                params={"receive_id_type": "chat_id"},
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "receive_id": chat_id,
                    "msg_type": "text",
                    "content": json.dumps({"text": text}, ensure_ascii=False),
                },
            )
            data = resp.json()
            if data.get("code") != 0:
                logger.error("Feishu send_text failed [%s]: %s", str(role), data)
                return None
            return (data.get("data") or {}).get("message_id")

    async def upload_image(self, path: str, *, role: str = "strategy") -> str | None:
        token = await self.get_tenant_access_token(role)
        if not token:
            return None
        from pathlib import Path

        file_path = Path(path).expanduser()
        if not file_path.is_file():
            from matrixsolo.config import get_settings as _gs

            alt = _gs().data_dir / "exports" / "covers" / file_path.name
            if alt.is_file():
                file_path = alt
        if not file_path.is_file():
            logger.error("Feishu upload_image missing file: %s", path)
            return None
        file_path = file_path.resolve()
        suffix = file_path.suffix.lower()
        mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}.get(
            suffix, "image/png"
        )
        async with httpx.AsyncClient(timeout=60.0) as client:
            with file_path.open("rb") as handle:
                resp = await client.post(
                    "https://open.feishu.cn/open-apis/im/v1/images",
                    headers={"Authorization": f"Bearer {token}"},
                    data={"image_type": "message"},
                    files={"image": (file_path.name, handle, mime)},
                )
            data = resp.json() if resp.content else {}
            if data.get("code") != 0:
                logger.error("Feishu upload_image failed [%s]: %s", str(role), data)
                return None
            return (data.get("data") or {}).get("image_key")

    async def send_image(
        self,
        chat_id: str,
        path: str,
        *,
        role: str = "strategy",
    ) -> str | None:
        image_key = await self.upload_image(path, role=role)
        if not image_key:
            return None
        token = await self.get_tenant_access_token(role)
        if not token:
            return None
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://open.feishu.cn/open-apis/im/v1/messages",
                params={"receive_id_type": "chat_id"},
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "receive_id": chat_id,
                    "msg_type": "image",
                    "content": json.dumps({"image_key": image_key}, ensure_ascii=False),
                },
            )
            data = resp.json()
            if data.get("code") != 0:
                logger.error("Feishu send_image failed [%s]: %s", str(role), data)
                return None
            return (data.get("data") or {}).get("message_id")

    async def reply_image(
        self,
        message_id: str,
        path: str,
        *,
        role: str = "strategy",
    ) -> bool:
        image_key = await self.upload_image(path, role=role)
        if not image_key:
            return False
        token = await self.get_tenant_access_token(role)
        if not token:
            return False
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "msg_type": "image",
                    "content": json.dumps({"image_key": image_key}, ensure_ascii=False),
                },
            )
            data = resp.json()
            if data.get("code") != 0:
                logger.error("Feishu reply_image failed [%s]: %s", str(role), data)
                return False
            return True

    async def download_message_file(
        self,
        message_id: str,
        file_key: str,
        *,
        role: str = "strategy",
        resource_type: str = "file",
    ) -> bytes | None:
        token = await self.get_tenant_access_token(role)
        if not token:
            return None
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(
                f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/resources/{file_key}",
                params={"type": resource_type},
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code >= 400:
                logger.error("Feishu file download failed [%s]: %s", str(role), resp.status_code)
                return None
            ctype = resp.headers.get("content-type", "")
            if "json" in ctype:
                try:
                    payload = resp.json()
                except Exception:  # noqa: BLE001
                    payload = {}
                if isinstance(payload, dict) and payload.get("code") not in (0, None):
                    logger.error("Feishu file download error [%s]: %s", str(role), payload)
                    return None
            return resp.content

    async def upsert_task_record(self, state: WorkflowState) -> None:
        s = self.settings
        role = "ops"
        if not (self.configured(role) and s.feishu_bitable_app_token and s.feishu_table_tasks):
            return
        token = await self.get_tenant_access_token(role)
        if not token:
            return
        fields = {
            "workflow_id": state.workflow_id,
            "status": state.status.value,
            "film": state.selected_topic.film_name if state.selected_topic else "",
            "title": (state.script.selected_title if state.script else "") or "",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            await client.post(
                f"https://open.feishu.cn/open-apis/bitable/v1/apps/{s.feishu_bitable_app_token}"
                f"/tables/{s.feishu_table_tasks}/records",
                headers={"Authorization": f"Bearer {token}"},
                json={"fields": fields},
            )

    async def write_calendar(self, rows: list[dict[str, Any]]) -> None:
        import os

        if os.environ.get("PYTEST_CURRENT_TEST"):
            return
        s = self.settings
        role = "strategy"
        if not (
            self.configured(role)
            and s.feishu_bitable_app_token
            and s.feishu_table_content_calendar
        ):
            return
        token = await self.get_tenant_access_token(role)
        if not token:
            return
        async with httpx.AsyncClient(timeout=30.0) as client:
            for row in rows:
                await client.post(
                    f"https://open.feishu.cn/open-apis/bitable/v1/apps/{s.feishu_bitable_app_token}"
                    f"/tables/{s.feishu_table_content_calendar}/records",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"fields": row},
                )

    async def write_work_log(self, log: Any) -> None:
        """每日工作记录写飞书多维表（FEISHU_TABLE_WORK_LOGS）。未配置则静默跳过。"""
        import os

        if os.environ.get("PYTEST_CURRENT_TEST"):
            return
        s = self.settings
        role = "strategy"
        if not (
            self.configured(role)
            and s.feishu_bitable_app_token
            and s.feishu_table_work_logs
        ):
            return
        token = await self.get_tenant_access_token(role)
        if not token:
            return
        fields = {
            "记录ID": log.log_id,
            "日期": log.date,
            "部门": log.department_name,
            "员工": log.employee_title,
            "项目": log.project,
            "类型": log.work_type,
            "状态": log.status,
            "摘要": log.summary,
            "产出链接": log.artifact_url,
            "工作流ID": log.workflow_id,
        }
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                await client.post(
                    f"https://open.feishu.cn/open-apis/bitable/v1/apps/{s.feishu_bitable_app_token}"
                    f"/tables/{s.feishu_table_work_logs}/records",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"fields": fields},
                )
        except Exception:
            logger.exception("write_work_log feishu failed")

    async def verify_all_tokens(self) -> dict[str, Any]:
        """探测五岗 tenant_access_token 是否可用."""
        result: dict[str, Any] = {}
        for role in resolve_staff_apps():
            app = self.app_for(role)
            token = await self.get_tenant_access_token(role)
            result[str(role)] = {
                "title": app.title,
                "app_id": app.app_id,
                "ok": bool(token),
            }
        return result
