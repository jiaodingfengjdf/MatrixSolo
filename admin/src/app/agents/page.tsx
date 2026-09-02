"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type AgentProfile } from "@/lib/api";

export default function AgentsPage() {
  const [items, setItems] = useState<AgentProfile[]>([]);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");

  const load = () =>
    api
      .listAgents()
      .then((d) => setItems(d.items))
      .catch((e: Error) => setError(e.message));

  useEffect(() => {
    load();
  }, []);

  const reset = async () => {
    if (!confirm("确认重置为默认五岗配置？")) return;
    await api.resetAgents();
    setToast("已重置默认配置");
    await load();
  };

  if (error) return <p className="error">{error}</p>;

  return (
    <>
      <h1 className="page-title">岗位 Agent</h1>
      <p className="page-sub">编辑人设、职业能力、记忆、做事风格、能力边界与系统提示词</p>
      <div className="actions" style={{ marginTop: 0, marginBottom: 16 }}>
        <button type="button" className="secondary" onClick={reset}>
          重置默认配置
        </button>
      </div>
      <div className="grid">
        {items.map((a) => (
          <Link className="card" key={a.role} href={`/agents/${a.role}`}>
            <h3>
              {a.title} <span className="meta">/{a.role}</span>
            </h3>
            <p className="meta">
              {a.llm.provider} · {a.llm.model}
            </p>
            <p className="meta">
              {(a.identity || "").split("\n")[0] || a.role}
            </p>
            <p className="meta">
              Skills {a.skills.length} · MCP {a.mcp_servers?.length || 0}
            </p>
            <span className={`badge ${a.enabled ? "on" : "off"}`}>
              {a.enabled ? "启用" : "禁用"}
            </span>
          </Link>
        ))}
      </div>
      {toast ? <div className="toast">{toast}</div> : null}
    </>
  );
}
