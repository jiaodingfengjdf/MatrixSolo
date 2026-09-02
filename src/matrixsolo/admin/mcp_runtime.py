from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

import httpx

from matrixsolo.admin.models import McpServerConfig
from matrixsolo.admin.store import get_profile_store

logger = logging.getLogger(__name__)


class RoleMcpRuntime:
    """按岗位加载已启用 MCP 配置，列举/调用工具（不可达时安全降级）。"""

    def __init__(self, role: str) -> None:
        self.role = role
        self.profile = get_profile_store().get_or_create(role)

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
        from matrixsolo.admin.tool_audit import get_tool_audit_store

        server = next((s for s in self.servers if s.id == server_id), None)
        if not server:
            return {"ok": False, "error": f"mcp server not found or disabled: {server_id}"}
        started = time.perf_counter()
        result = await self._call_server_tool(server, tool_name, arguments or {})
        try:
            get_tool_audit_store().append(
                employee_id=self.role,
                tool=tool_name,
                kind="mcp",
                ok=bool(result.get("ok")),
                error=str(result.get("error") or ""),
                duration_ms=(time.perf_counter() - started) * 1000,
                params=arguments or {},
                extra={"server": server.name, "transport": server.transport},
            )
        except Exception:
            logger.exception("mcp audit failed")
        return result

    async def _list_server_tools(self, server: McpServerConfig) -> list[dict[str, Any]]:
        try:
            if server.transport in ("http", "sse") and server.url:
                return await self._http_list_tools(server)
            if server.transport == "stdio":
                return await self._stdio_list_tools(server)
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
            if server.transport == "stdio":
                return await self._stdio_call_tool(server, tool_name, arguments)
            return {
                "ok": False,
                "error": f"transport {server.transport} call not available in this runtime stub",
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("MCP call failed [%s/%s]: %s", server.name, tool_name, exc)
            return {"ok": False, "error": str(exc)}

    async def _stdio_list_tools(self, server: McpServerConfig) -> list[dict[str, Any]]:
        result = await _stdio_rpc(server, "tools/list", {}, timeout=10.0)
        if result.get("ok") is False:
            return [
                {
                    "server_id": server.id,
                    "server_name": server.name,
                    "name": "_unreachable",
                    "description": f"stdio unreachable: {result.get('error')}",
                    "error": str(result.get("error")),
                }
            ]
        tools = ((result.get("result") or {}).get("tools") or [])
        return [
            {
                "server_id": server.id,
                "server_name": server.name,
                "name": t.get("name", ""),
                "description": t.get("description", ""),
            }
            for t in tools
            if isinstance(t, dict) and t.get("name")
        ]

    async def _stdio_call_tool(
        self,
        server: McpServerConfig,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        result = await _stdio_rpc(
            server,
            "tools/call",
            {"name": tool_name, "arguments": arguments},
            timeout=30.0,
        )
        if result.get("ok") is False:
            return {"ok": False, "error": str(result.get("error") or "stdio call failed")}
        content = (result.get("result") or {}).get("content") or []
        text = "\n".join(
            str(block.get("text") or block.get("value") or json.dumps(block, ensure_ascii=False))
            for block in content
            if isinstance(block, dict)
        )[:4000]
        return {"ok": True, "server": server.name, "result": {"text": text or "ok"}}


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


async def _stdio_rpc(
    server: McpServerConfig,
    method: str,
    params: dict[str, Any],
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """最小 stdio JSON-RPC 客户端：initialize → notifications/initialized → method."""
    if not server.command:
        return {"ok": False, "error": "stdio 未配置 command"}
    env = {**os.environ, **server.env}
    try:
        proc = await asyncio.create_subprocess_exec(
            server.command,
            *server.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"start stdio failed: {exc}"}

    stderr_buf: list[str] = []

    async def _drain_stderr() -> None:
        try:
            data = await proc.stderr.read()
            if data:
                stderr_buf.append(data.decode("utf-8", errors="replace"))
        except Exception:  # noqa: BLE001
            logger.debug("stdio stderr drain failed")

    stderr_task = asyncio.create_task(_drain_stderr())

    async def send(msg: dict[str, Any]) -> None:
        if proc.stdin is None:
            raise RuntimeError("stdio stdin closed")
        proc.stdin.write((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
        await proc.stdin.drain()

    async def recv(rid: int) -> dict[str, Any]:
        if proc.stdout is None:
            raise RuntimeError("stdio stdout closed")
        while True:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout)
            if not line:
                raise RuntimeError("stdio closed by server")
            try:
                msg = json.loads(line.decode("utf-8", errors="replace").strip())
            except json.JSONDecodeError:
                continue
            if not isinstance(msg, dict):
                continue
            if msg.get("id") == rid:
                if msg.get("error"):
                    raise RuntimeError(str(msg["error"]))
                return msg.get("result") or {}

    try:
        await send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "matrixsolo", "version": "0.1.0"},
                },
            }
        )
        await recv(1)
        await send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        await send({"jsonrpc": "2.0", "id": 2, "method": method, "params": params})
        result = await recv(2)
        return {"ok": True, "result": result}
    except TimeoutError:
        return {"ok": False, "error": f"stdio {method} timeout(s)"}
    except Exception as exc:  # noqa: BLE001
        detail = str(exc)
        if stderr_buf:
            detail += " | stderr: " + stderr_buf[-1][:500]
        return {"ok": False, "error": detail}
    finally:
        try:
            proc.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        if stderr_task and not stderr_task.done():
            stderr_task.cancel()
