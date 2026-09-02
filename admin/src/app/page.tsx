"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type StudioPrompt, type WorkLog } from "@/lib/api";

type Overview = {
  hitl_chat_id?: string;
  today?: string;
  today_work_logs?: number;
  work_logs_feishu_configured?: boolean;
  work_logs?: WorkLog[];
  blocked_hitl?: Array<{ workflow_id: string; status: string; film?: string; last_log?: string }>;
  feishu_staff?: Record<string, { title: string; configured: boolean; app_id: string }>;
  agents?: Array<{
    role: string;
    title: string;
    enabled: boolean;
    llm: { provider: string };
    tools_enabled: string[];
    skills_count: number;
    mcp_count: number;
  }>;
};

export default function OverviewPage() {
  const [data, setData] = useState<Overview | null>(null);
  const [studio, setStudio] = useState<StudioPrompt | null>(null);
  const [toast, setToast] = useState("");
  const [savingStudio, setSavingStudio] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .overview()
      .then((d) => setData(d as Overview))
      .catch((e: Error) => setError(e.message));
    api
      .getPromptStudio()
      .then((s) => setStudio(s))
      .catch(() => setStudio(null));
  }, []);

  const saveStudio = async () => {
    if (!studio) return;
    setSavingStudio(true);
    try {
      const updated = await api.updatePromptStudio({
        studio_voice: studio.studio_voice,
        colleagues: studio.colleagues,
      });
      setStudio(updated);
      setToast("工作室守则已保存，未改动的岗位预览立即继承。");
    } catch (e) {
      setToast((e as Error).message);
    } finally {
      setSavingStudio(false);
    }
  };

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p className="meta">加载中…</p>;

  const blocked = data.blocked_hitl || [];
  const configured = data.work_logs_feishu_configured;

  return (
    <>
      <h1 className="page-title">系统总览</h1>
      <p className="page-sub">可配置数字影视工作室 · HITL 关键决策，执行层多模型与工具</p>

      <div className="grid" style={{ marginBottom: 16 }}>
        <div className="card">
          <h3>今日工作记录</h3>
          <p style={{ fontSize: "2rem", margin: "6px 0" }}>{data.today_work_logs ?? 0}</p>
          <span className="meta">业务日 {data.today || "—"}</span>
        </div>
        <div className="card">
          <h3>待审批 HITL</h3>
          <p style={{ fontSize: "2rem", margin: "6px 0" }}>{blocked.length}</p>
          <span className="meta">选题 / 脚本 / 成片</span>
        </div>
        <div className="card">
          <h3>飞书审批群</h3>
          <p className="meta" style={{ marginTop: 8 }}>
            <code>{data.hitl_chat_id || "未配置"}</code>
          </p>
          {configured ? (
            <span className="badge on">多维表已配置</span>
          ) : (
            <span className="badge off">WORK_LOGS 表未配置 · 仅本地</span>
          )}
        </div>
      </div>

      {!configured && (
        <div className="panel" style={{ borderColor: "var(--accent)" }}>
          <p className="meta" style={{ margin: 0 }}>
            当前未配置 <code>FEISHU_TABLE_WORK_LOGS</code>，工作记录仅写入本地
            <code>data/admin/work_logs.jsonl</code>。
          </p>
        </div>
      )}

      <div className="panel">
        <h2>飞书 HITL 员工</h2>
        <div className="grid">
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
        <h2>岗位 / 员工</h2>
        <div className="grid">
          {(data.agents || []).map((a) => (
            <Link className="card" key={a.role} href={`/agents/${a.role}`}>
              <h3>{a.title}</h3>
              <p className="meta">
                {a.llm.provider} / 模型中心
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

      <div className="panel">
        <h2>今日工作记录</h2>
        {(data.work_logs || []).length === 0 ? (
          <p className="meta">暂无。跑一次群内开工或 HITL 后自动入库。</p>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>项目</th>
                  <th>类型</th>
                  <th>状态</th>
                  <th>摘要</th>
                </tr>
              </thead>
              <tbody>
                {(data.work_logs || []).slice(0, 12).map((w) => (
                  <tr key={w.log_id}>
                    <td>{w.project}</td>
                    <td>{w.work_type}</td>
                    <td>
                      <span className={`badge ${w.status === "done" ? "on" : "off"}`}>
                        {w.status}
                      </span>
                    </td>
                    <td className="meta">{w.summary}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Link className="link" href="/worklogs" style={{ display: "inline-block", marginTop: 10 }}>
          打开工作记录 →
        </Link>
      </div>

      <div className="panel">
        <h2>待审批 HITL</h2>
        {blocked.length === 0 ? (
          <p className="meta">没有阻塞中的审批卡片。</p>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>工作流</th>
                  <th>阶段</th>
                  <th>项目</th>
                  <th>最新日志</th>
                </tr>
              </thead>
              <tbody>
                {blocked.map((b) => (
                  <tr key={b.workflow_id}>
                    <td>
                      <Link className="link" href={`/workflows`}>
                        {b.workflow_id.slice(0, 8)}
                      </Link>
                    </td>
                    <td>{b.status}</td>
                    <td>{b.film || "—"}</td>
                    <td className="meta">{b.last_log || ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="panel">
        <h2>工作室守则 (L0) · Prompt OS</h2>
        <p className="meta">修改后所有岗位预览与真实注入立即继承，无需逐岗粘贴。</p>
        <div className="form-grid" style={{ marginTop: 12 }}>
          <label>
            活人感守则
            <textarea
              rows={6}
              value={studio?.studio_voice || ""}
              onChange={(e) => setStudio(studio ? { ...studio, studio_voice: e.target.value } : studio)}
            />
          </label>
          <label>
            工作室共识 / 同事花名
            <textarea
              rows={6}
              value={studio?.colleagues || ""}
              onChange={(e) => setStudio(studio ? { ...studio, colleagues: e.target.value } : studio)}
            />
          </label>
        </div>
        <div className="form-row" style={{ marginTop: 8 }}>
          <button onClick={() => void saveStudio()} disabled={savingStudio}>
            {savingStudio ? "保存中…" : "保存守则"}
          </button>
        </div>
      </div>

      {toast && <p className="meta">{toast}</p>}
    </>
  );
}
