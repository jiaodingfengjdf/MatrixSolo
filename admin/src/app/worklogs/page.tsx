"use client";

import { useEffect, useState } from "react";
import { api, type WorkLog } from "@/lib/api";

const WORK_TYPES = ["huddle", "hitl", "workflow", "manual"];
const STATUSES = ["started", "blocked", "done", "failed"];

export default function WorkLogsPage() {
  const [items, setItems] = useState<WorkLog[]>([]);
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState({
    project: "",
    work_type: "manual",
    status: "done",
    summary: "",
    employee_id: "",
    employee_title: "",
  });
  const [toast, setToast] = useState("");

  const load = async (extra: Record<string, string> = {}) => {
    try {
      const params = { ...filters, ...extra, limit: 500 };
      const r = await api.listWorkLogs(params);
      setItems(r.items);
    } catch (e) {
      setToast((e as Error).message);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = async () => {
    try {
      await api.createWorkLog(form as Partial<WorkLog>);
      setToast("已补记一行工作记录。");
      setFormOpen(false);
      setForm({ project: "", work_type: "manual", status: "done", summary: "", employee_id: "", employee_title: "" });
      await load();
    } catch (e) {
      setToast((e as Error).message);
    }
  };

  const setFilter = (k: string, v: string) => {
    const next = { ...filters, [k]: v };
    setFilters(next);
    load(next);
  };

  return (
    <>
      <h1 className="page-title">工作记录</h1>
      <p className="page-sub">每日项目流水与复盘 · 本地镜像 + 可选飞书多维表 WRK_LOGS</p>

      <div className="panel">
        <div className="form-row" style={{ marginBottom: 12 }}>
          <label>
            开始日期
            <input type="date" onChange={(e) => setFilter("date_from", e.target.value)} />
          </label>
          <label>
            结束日期
            <input type="date" onChange={(e) => setFilter("date_to", e.target.value)} />
          </label>
          <label>
            类型
            <select onChange={(e) => setFilter("work_type", e.target.value)}>
              <option value="">全部</option>
              {WORK_TYPES.map((w) => (
                <option value={w} key={w}>{w}</option>
              ))}
            </select>
          </label>
          <label>
            状态
            <select onChange={(e) => setFilter("status", e.target.value)}>
              <option value="">全部</option>
              {STATUSES.map((s) => (
                <option value={s} key={s}>{s}</option>
              ))}
            </select>
          </label>
          <label>
            员工
            <input placeholder="employee_id" onChange={(e) => setFilter("employee_id", e.target.value)} />
          </label>
        </div>
        <div className="actions">
          <button onClick={() => setFormOpen((v) => !v)}>补记一行</button>
        </div>

        {formOpen && (
          <div className="form-grid" style={{ marginTop: 12 }}>
            <div className="form-row">
              <label>
                项目
                <input value={form.project} onChange={(e) => setForm({ ...form, project: e.target.value })} />
              </label>
              <label>
                类型
                <select value={form.work_type} onChange={(e) => setForm({ ...form, work_type: e.target.value })}>
                  {WORK_TYPES.map((w) => (
                    <option value={w} key={w}>{w}</option>
                  ))}
                </select>
              </label>
              <label>
                状态
                <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                  {STATUSES.map((s) => (
                    <option value={s} key={s}>{s}</option>
                  ))}
                </select>
              </label>
            </div>
            <div className="form-row">
              <label>
                员工 ID
                <input value={form.employee_id} onChange={(e) => setForm({ ...form, employee_id: e.target.value })} />
              </label>
              <label>
                员工名
                <input value={form.employee_title} onChange={(e) => setForm({ ...form, employee_title: e.target.value })} />
              </label>
            </div>
            <label>
              摘要
              <textarea rows={3} value={form.summary} onChange={(e) => setForm({ ...form, summary: e.target.value })} />
            </label>
            <button onClick={() => void submit()}>保存</button>
          </div>
        )}

        <div className="table-wrap" style={{ marginTop: 12 }}>
          <table className="data">
            <thead>
              <tr>
                <th>日期</th>
                <th>项目</th>
                <th>类型</th>
                <th>状态</th>
                <th>员工</th>
                <th>摘要</th>
                <th>工作流</th>
              </tr>
            </thead>
            <tbody>
              {items.map((w) => (
                <tr key={w.log_id}>
                  <td>{w.date}</td>
                  <td>{w.project}</td>
                  <td>{w.work_type}</td>
                  <td>
                    <span className={`badge ${w.status === "done" ? "on" : "off"}`}>{w.status}</span>
                  </td>
                  <td>{w.employee_title || w.employee_id || "—"}</td>
                  <td className="meta">{w.summary}</td>
                  <td className="meta">{w.workflow_id ? w.workflow_id.slice(0, 8) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {items.length === 0 && <p className="meta">暂无记录。</p>}
      </div>

      {toast && <p className="meta">{toast}</p>}
    </>
  );
}
