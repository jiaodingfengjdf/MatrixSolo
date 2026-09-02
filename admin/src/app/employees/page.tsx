"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type Employee, type PolishDraft } from "@/lib/api";

const FUNCTIONS = ["strategy", "script", "visual", "editor", "ops"];
const POLISH_FIELDS = [
  "identity",
  "personality",
  "craft",
  "work_style",
  "memory",
  "capability_boundary",
  "system_prompt",
] as const;
const FIELD_LABEL: Record<string, string> = {
  identity: "身份",
  personality: "性格",
  craft: "职业能力",
  work_style: "做事风格",
  memory: "长期记忆",
  capability_boundary: "能力边界（可做/不可做/越界话术）",
  system_prompt: "任务契约（管线 + 对话）",
};

export default function EmployeesPage() {
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState({
    id: "",
    title: "",
    display_name: "",
    function: "script",
    app_id: "",
    app_secret: "",
  });
  const [polishTarget, setPolishTarget] = useState<Employee | null>(null);
  const [oneLiner, setOneLiner] = useState("");
  const [draft, setDraft] = useState<PolishDraft | null>(null);
  const [toast, setToast] = useState("");

  const load = async () => {
    try {
      const r = await api.listEmployees();
      setEmployees(r.items);
    } catch (e) {
      setToast((e as Error).message);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const onboard = async () => {
    if (!form.id || !form.title) return;
    try {
      await api.createEmployee({ ...form, app_secret: form.app_secret });
      setToast(`已入职「${form.title}」，下一步一键润色。`);
      setFormOpen(false);
      setForm({ id: "", title: "", display_name: "", function: "script", app_id: "", app_secret: "" });
      await load();
    } catch (e) {
      setToast((e as Error).message);
    }
  };

  const runPolish = async (emp: Employee) => {
    setPolishTarget(emp);
    setDraft(null);
    try {
      setToast("正在生成人设草稿…");
      const d = await api.polishEmployee(emp.id, {
        one_liner: oneLiner,
        department: "默认",
      });
      setDraft(d);
      setToast(d.llm_generated ? "草稿已生成，可逐项编辑。" : "模型未配置，已返回专业骨架。");
    } catch (e) {
      setToast((e as Error).message);
    }
  };

  const applyDraft = async () => {
    if (!polishTarget || !draft) return;
    try {
      await api.applyPolish(polishTarget.id, draft.draft);
      setToast(`「${polishTarget.title}」人设已生效，可在岗位页编辑/回滚。`);
      setPolishTarget(null);
      setDraft(null);
      await load();
    } catch (e) {
      setToast((e as Error).message);
    }
  };

  const toggleEnabled = async (emp: Employee) => {
    try {
      await (emp.enabled ? api.disableEmployee(emp.id) : api.enableEmployee(emp.id));
      await load();
    } catch (e) {
      setToast((e as Error).message);
    }
  };

  const reload = async () => {
    try {
      await api.reloadWorkers();
      setToast("已按员工注册表重载飞书长连接。");
    } catch (e) {
      setToast((e as Error).message);
    }
  };

  return (
    <>
      <h1 className="page-title">员工</h1>
      <p className="page-sub">
        飞书开放平台先建智能体 → 后台入职贴凭证 → 一键润色 → 编辑保存 → 上岗
      </p>

      <div className="panel">
        <div className="actions" style={{ marginBottom: 12 }}>
          <button onClick={() => setFormOpen((v) => !v)}>入职新员工</button>
          <button className="secondary" onClick={() => void reload()}>重载长连接</button>
        </div>
        {formOpen && (
          <div className="form-grid" style={{ marginBottom: 16 }}>
            <div className="form-row">
              <label>
                employee_id（slug）
                <input value={form.id} onChange={(e) => setForm({ ...form, id: e.target.value })} placeholder="headline_editor" />
              </label>
              <label>
                花名
                <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="头条编辑" />
              </label>
              <label>
                飞书应用名（可选）
                <input value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
              </label>
              <label>
                职能标签
                <select value={form.function} onChange={(e) => setForm({ ...form, function: e.target.value })}>
                  {FUNCTIONS.map((f) => (
                    <option value={f} key={f}>{f}</option>
                  ))}
                  <option value="custom">自定义</option>
                </select>
              </label>
            </div>
            <div className="form-row">
              <label>
                app_id
                <input value={form.app_id} onChange={(e) => setForm({ ...form, app_id: e.target.value })} placeholder="cli_xxx" />
              </label>
              <label>
                app_secret
                <input type="password" value={form.app_secret} onChange={(e) => setForm({ ...form, app_secret: e.target.value })} />
              </label>
            </div>
            <button onClick={() => void onboard()}>入职</button>
          </div>
        )}

        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>花名</th>
                <th>ID</th>
                <th>职能</th>
                <th>凭证</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {employees.map((emp) => (
                <tr key={emp.id}>
                  <td>{emp.title}</td>
                  <td className="meta">{emp.id}</td>
                  <td>{emp.function}</td>
                  <td className="meta">{emp.has_credentials ? "已配置" : "未配置"}</td>
                  <td>
                    <span className={`badge ${emp.enabled ? "on" : "off"}`}>
                      {emp.enabled ? "在职" : "已停用"}
                    </span>
                  </td>
                  <td>
                    <button className="secondary" onClick={() => void runPolish(emp)}>一键润色</button>{" "}
                    <Link className="link" href={`/agents/${emp.id}`}>编辑人设</Link>{" "}
                    <button className="secondary" onClick={() => void toggleEnabled(emp)}>
                      {emp.enabled ? "停用" : "启用"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {polishTarget && (
        <div className="panel" style={{ borderColor: "var(--accent)" }}>
          <h2>一键润色 · {polishTarget.title}</h2>
          <div className="form-row">
            <label>
              一句话职责
              <input value={oneLiner} onChange={(e) => setOneLiner(e.target.value)} placeholder="负责头条图文与封面协作" />
            </label>
            <div style={{ alignSelf: "end" }}>
              <button onClick={() => void runPolish(polishTarget)} disabled={!draft}>重新生成</button>
            </div>
          </div>
          {draft && (
            <>
              <div className="form-grid" style={{ marginTop: 12 }}>
                {POLISH_FIELDS.map((field) => (
                  <label key={field}>
                    {FIELD_LABEL[field]}
                    <textarea
                      rows={3}
                      value={draft.draft[field] || ""}
                      onChange={(e) =>
                        setDraft({ ...draft, draft: { ...draft.draft, [field]: e.target.value } })
                      }
                    />
                  </label>
                ))}
              </div>
              <div className="actions" style={{ marginTop: 8 }}>
                <button onClick={() => void applyDraft()}>确认保存（可回滚）</button>
                <button className="secondary" onClick={() => { setPolishTarget(null); setDraft(null); }}>
                  取消
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {toast && <p className="meta">{toast}</p>}
    </>
  );
}
