"use client";

import { useEffect, useState } from "react";
import { api, type ToolAudit } from "@/lib/api";

export default function AuditPage() {
  const [items, setItems] = useState<ToolAudit[]>([]);
  const [kind, setKind] = useState("");
  const [toast, setToast] = useState("");

  const load = async (k = kind) => {
    try {
      const r = await api.listToolAudit({ kind: k, limit: 500 });
      setItems(r.items);
    } catch (e) {
      setToast((e as Error).message);
    }
  };

  useEffect(() => {
    load("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <>
      <h1 className="page-title">工具审计</h1>
      <p className="page-sub">谁、何时、调了哪个 Skill / MCP 工具，成功还是超时</p>

      <div className="panel">
        <div className="form-row" style={{ marginBottom: 12 }}>
          <label>
            类型
            <select
              value={kind}
              onChange={(e) => {
                setKind(e.target.value);
                load(e.target.value);
              }}
            >
              <option value="">全部</option>
              <option value="runtime">Skill Runtime</option>
              <option value="mcp">MCP</option>
            </select>
          </label>
        </div>

        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>时间</th>
                <th>员工</th>
                <th>类型</th>
                <th>工具</th>
                <th>结果</th>
                <th>耗时</th>
                <th>错误</th>
              </tr>
            </thead>
            <tbody>
              {items.map((row, i) => (
                <tr key={`${row.ts}-${i}`}>
                  <td className="meta">{row.ts}</td>
                  <td>{row.employee_id}</td>
                  <td>{row.kind}</td>
                  <td>{row.tool}</td>
                  <td>
                    <span className={`badge ${row.ok ? "on" : "off"}`}>{row.ok ? "成功" : "失败"}</span>
                  </td>
                  <td className="meta">{row.duration_ms}ms</td>
                  <td className="meta">{row.error || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {items.length === 0 && <p className="meta">暂无审计记录。</p>}
      </div>

      {toast && <p className="meta">{toast}</p>}
    </>
  );
}
