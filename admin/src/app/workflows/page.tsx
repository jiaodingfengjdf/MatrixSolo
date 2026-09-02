"use client";

import { useEffect, useState } from "react";
import { api, type StudioBoard } from "@/lib/api";

export default function WorkflowsPage() {
  const [board, setBoard] = useState<StudioBoard | null>(null);
  const [error, setError] = useState("");
  const [activeId, setActiveId] = useState("");
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null);

  const load = () =>
    api
      .studioBoard()
      .then(setBoard)
      .catch((e: Error) => setError(e.message));

  useEffect(() => {
    load();
    const timer = window.setInterval(load, 8000);
    return () => window.clearInterval(timer);
  }, []);

  const open = async (id: string) => {
    setActiveId(id);
    try {
      setDetail(await api.getWorkflow(id));
    } catch (e) {
      setDetail({ error: e instanceof Error ? e.message : "无法读取工作流" });
    }
  };

  if (error) return <p className="error">{error}</p>;
  if (!board) return <p className="meta">加载中…</p>;

  const huddle = board.huddle || {};
  const logs = Array.isArray(detail?.logs) ? (detail?.logs as string[]) : [];

  return (
    <>
      <h1 className="page-title">工作流看板</h1>
      <p className="page-sub">HITL 卡在哪、huddle 最近一期、飞书认领痕迹</p>

      <div className="panel">
        <h2>最近一期 huddle</h2>
        {board.huddle ? (
          <>
            <p>
              <span className="badge on">{String(huddle.job || "talk")}</span>{" "}
              {String(huddle.film_name || "-")}
            </p>
            <p className="meta">
              切口 {String(huddle.angle || "-")} · 情绪 {String(huddle.mood || "-")}
            </p>
            <p className="meta">{String(huddle.user_text || "")}</p>
            <p className="meta">{String(huddle.ts || "")}</p>
          </>
        ) : (
          <p className="meta">还没有群 huddle 记录。</p>
        )}
      </div>

      <div className="panel">
        <h2>工作流</h2>
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>状态</th>
                <th>触发</th>
                <th>主题</th>
                <th>封面</th>
                <th>更新</th>
                <th>最后日志</th>
              </tr>
            </thead>
            <tbody>
              {board.workflows.map((row) => (
                <tr
                  key={row.workflow_id}
                  className={row.workflow_id === activeId ? "active" : ""}
                  onClick={() => open(row.workflow_id)}
                >
                  <td>
                    <span
                      className={`badge ${
                        row.status?.includes("awaiting") ? "off" : "on"
                      }`}
                    >
                      {row.status}
                    </span>
                  </td>
                  <td>{row.trigger || "—"}</td>
                  <td>{row.film || "—"}</td>
                  <td>{row.cover_count ?? 0}</td>
                  <td className="meta">{(row.updated_at || "").slice(0, 19)}</td>
                  <td className="meta">{row.last_log || ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!board.workflows.length ? <p className="meta">暂无工作流。</p> : null}
      </div>

      {detail ? (
        <div className="panel">
          <h2>详情 {String(detail.workflow_id || activeId)}</h2>
          <p className="meta">
            预览：{String((detail.render as { preview_path?: string } | undefined)?.preview_path || "无")}
          </p>
          {(detail.errors as string[] | undefined)?.length ? (
            <p className="error">{(detail.errors as string[]).join("；")}</p>
          ) : null}
          <pre className="log">{logs.slice(-24).join("\n") || "无日志"}</pre>
        </div>
      ) : null}

      <div className="panel">
        <h2>内容日历（本地）</h2>
        {board.calendar.length ? (
          <ul>
            {board.calendar.slice(0, 8).map((row, i) => (
              <li key={i} className="meta">
                {String(row.date || "")} {String(row.slot || "")} · {String(row.film || "")}
              </li>
            ))}
          </ul>
        ) : (
          <p className="meta">还没有日历行。选题或 huddle 出图后会写入。</p>
        )}
      </div>

      <div className="panel">
        <h2>飞书入站痕迹</h2>
        <pre className="log">
          {board.feishu_trace
            .slice(0, 20)
            .map((row) => JSON.stringify(row, null, 0))
            .join("\n") || "暂无"}
        </pre>
      </div>
    </>
  );
}
