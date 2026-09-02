from __future__ import annotations

import logging
from typing import Any

import httpx

from matrixsolo.admin.models import McpServerConfig
from matrixsolo.admin.store import get_profile_store

logger = logging.getLogger(__name__)


class RoleMcpRuntime:
    """按岗位加载已启用 MCP 配置，列举/调用工具（不可达时安全降级）。"""

    def __init__(self, role: str) -> None:
        self.role = role
        self.profile = get_profile_store().get(role)

    @property
    def servers(self) -> list[McpServerConfig]:
        return [s for s in self.profile.mcp_servers if s.enabled]

    async def list_tools(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        for server in self.servers:
            tools.extend(await self._list_server_tools(server))
        return tools

    async def call_tool(
        self,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        server = next((s for s in self.servers if s.id == server_id), None)
        if not server:
            return {"ok": False, "error": f"mcp server not found or disabled: {server_id}"}
        return await self._call_server_tool(server, tool_name, arguments or {})

    async def _list_server_tools(self, server: McpServerConfig) -> list[dict[str, Any]]:
        try:
            if server.transport in ("http", "sse") and server.url:
                return await self._http_list_tools(server)
            if server.transport == "stdio":
                # stdio 需要长连接进程；管理台探测阶段返回元数据占位
                return [
                    {
                        "server_id": server.id,
                        "server_name": server.name,
                        "name": "_stdio_placeholder",
                        "description": f"stdio MCP `{server.command}` — 运行时按需拉起",
                    }
                ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("MCP list_tools failed [%s/%s]: %s", self.role, server.name, exc)
            return [
                {
                    "server_id": server.id,
                    "server_name": server.name,
                    "name": "_unreachable",
                    "description": f"unreachable: {exc}",
                    "error": str(exc),
                }
            ]
        return []

    async def _http_list_tools(self, server: McpServerConfig) -> list[dict[str, Any]]:
        base = server.url.rstrip("/")
        async with httpx.AsyncClient(timeout=15.0) as client:
            # 兼容本地 MatrixSolo MCP HTTP 执行器 /tools
            resp = await client.get(f"{base}/tools")
            if resp.status_code == 200:
                data = resp.json()
                raw = data.get("tools") or data.get("items") or []
                out = []
                for t in raw:
                    if isinstance(t, str):
                        out.append(
                            {
                                "server_id": server.id,
                                "server_name": server.name,
                                "name": t,
                                "description": "",
                            }
                        )
                    elif isinstance(t, dict):
                        out.append(
                            {
                                "server_id": server.id,
                                "server_name": server.name,
                                "name": t.get("name") or t.get("tool") or "unknown",
                                "description": t.get("description") or "",
                            }
                        )
                return out
            # JSON-RPC tools/list 尝试
            rpc = await client.post(
                base,
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            )
            if rpc.status_code == 200:
                result = (rpc.json() or {}).get("result") or {}
                return [
                    {
                        "server_id": server.id,
                        "server_name": server.name,
                        "name": t.get("name", ""),
                        "description": t.get("description", ""),
                    }
                    for t in (result.get("tools") or [])
                ]
        return []

    async def _call_server_tool(
        self,
        server: McpServerConfig,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            if server.transport in ("http", "sse") and server.url:
                base = server.url.rstrip("/")
                async with httpx.AsyncClient(timeout=60.0) as client:
                    # 本地执行器风格: POST /tools/{name}
                    resp = await client.post(f"{base}/tools/{tool_name}", json=arguments)
                    if resp.status_code == 200:
                        return {"ok": True, "server": server.name, "result": resp.json()}
                    rpc = await client.post(
                        base,
                        json={
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "tools/call",
                            "params": {"name": tool_name, "arguments": arguments},
                        },
                    )
                    if rpc.status_code == 200:
                        return {"ok": True, "server": server.name, "result": rpc.json()}
                    return {
                        "ok": False,
                        "error": f"HTTP {resp.status_code}",
                        "body": resp.text[:500],
                    }
            return {
                "ok": False,
                "error": f"transport {server.transport} call not available in this runtime stub",
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("MCP call failed [%s/%s]: %s", server.name, tool_name, exc)
            return {"ok": False, "error": str(exc)}


async def enrich_with_mcp_context(role: str) -> str:
    """供 Agent 节点注入：列出可用 MCP 工具摘要。"""
    runtime = RoleMcpRuntime(role)
    if not runtime.servers:
        return ""
    tools = await runtime.list_tools()
    if not tools:
        return ""
    lines = [f"- {t.get('server_name')}/{t.get('name')}: {t.get('description') or ''}" for t in tools]
    return "可用 MCP 工具:\n" + "\n".join(lines)
