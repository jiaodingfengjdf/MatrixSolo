"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

type Overview = {
  hitl_chat_id?: string;
  feishu_staff?: Record<string, { title: string; configured: boolean; app_id: string }>;
  agents?: Array<{
    role: string;
    title: string;
    enabled: boolean;
    llm: { provider: string; model: string };
    tools_enabled: string[];
    skills_count: number;
    mcp_count: number;
  }>;
};

export default function OverviewPage() {
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .overview()
      .then((d) => setData(d as Overview))
      .catch((e: Error) => setError(e.message));
  }, []);

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p className="meta">加载中…</p>;

  return (
    <>
      <h1 className="page-title">系统总览</h1>
      <p className="page-sub">五岗 AI 员工 · 飞书 HITL · LangGraph 编排</p>

      <div className="panel">
        <h2>飞书 HITL</h2>
        <p className="meta">
          审批群 chat_id：<code>{data.hitl_chat_id || "未配置"}</code>
        </p>
        <div className="grid" style={{ marginTop: 12 }}>
          {Object.entries(data.feishu_staff || {}).map(([role, staff]) => (
            <div className="card" key={role}>
              <h3>{staff.title}</h3>
              <p className="meta">{staff.app_id || "—"}</p>
              <span className={`badge ${staff.configured ? "on" : "off"}`}>
                {staff.configured ? "已配置" : "未配置"}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div className="panel">
        <h2>岗位 Agent</h2>
        <div className="grid">
          {(data.agents || []).map((a) => (
            <Link className="card" key={a.role} href={`/agents/${a.role}`}>
              <h3>{a.title}</h3>
              <p className="meta">
                {a.llm.provider} / {a.llm.model}
              </p>
              <p className="meta">
                Skills {a.skills_count} · Tools {a.tools_enabled.length} · MCP {a.mcp_count}
              </p>
              <span className={`badge ${a.enabled ? "on" : "off"}`}>
                {a.enabled ? "启用" : "禁用"}
              </span>
            </Link>
          ))}
        </div>
      </div>
    </>
  );
}
