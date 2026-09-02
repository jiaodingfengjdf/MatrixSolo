"use client";

import { useEffect, useState } from "react";
import { api, type Department, type RecentChat } from "@/lib/api";

const MEMBER_OPTIONS = ["strategy", "script", "visual", "editor", "ops"];
const PLATFORMS: Record<string, string> = {
  toutiao: "今日头条",
  douyin: "抖音",
  bilibili: "哔哩哔哩",
  other: "其他",
};

export default function DepartmentsPage() {
  const [depts, setDepts] = useState<Department[]>([]);
  const [employees, setEmployees] = useState<Array<{ id: string; title: string }>>([]);
  const [recent, setRecent] = useState<RecentChat[]>([]);
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState({
    id: "",
    name: "",
    platform: "toutiao",
    member_employee_ids: [] as string[],
  });
  const [bindTarget, setBindTarget] = useState<Department | null>(null);
  const [bindChat, setBindChat] = useState("");
  const [toast, setToast] = useState("");

  const load = async () => {
    const [d, e, r] = await Promise.all([
      api.listDepartments(),
      api.listEmployees(),
      api.recentChats(),
    ]);
    setDepts(d.items);
    setEmployees(e.items.map((x) => ({ id: x.id, title: x.title })));
    setRecent(r.items);
  };

  useEffect(() => {
    load().catch((err) => setToast((err as Error).message));
  }, []);

  const create = async () => {
    if (!form.id || !form.name) return;
    try {
      await api.createDepartment({
        id: form.id,
        name: form.name,
        platform: form.platform as Department["platform"],
        member_employee_ids: form.member_employee_ids.length
          ? form.member_employee_ids
          : MEMBER_OPTIONS,
        pipeline_template: form.member_employee_ids.length
          ? form.member_employee_ids
          : MEMBER_OPTIONS,
      });
      setToast("部门已创建，接下来绑定工作群。");
      setFormOpen(false);
      setForm({ id: "", name: "", platform: "toutiao", member_employee_ids: [] });
      await load();
    } catch (e) {
      setToast((e as Error).message);
    }
  };

  const toggleMember = (id: string) => {
    setForm((f) => ({
      ...f,
      member_employee_ids: f.member_employee_ids.includes(id)
        ? f.member_employee_ids.filter((m) => m !== id)
        : [...f.member_employee_ids, id],
    }));
  };

  const bind = async () => {
    if (!bindTarget || !bindChat) return;
    try {
      await api.bindDepartmentChat(bindTarget.id, bindChat);
      setToast(`已绑定「${bindTarget.name}」← ${bindChat}`);
      setBindTarget(null);
      setBindChat("");
      await load();
    } catch (e) {
      setToast((e as Error).message);
    }
  };

  const unbind = async (d: Department) => {
    try {
      await api.unbindDepartmentChat(d.id);
      await load();
    } catch (e) {
      setToast((e as Error).message);
    }
  };

  const remove = async (d: Department) => {
    if (!confirm(`删除部门「${d.name}」？`)) return;
    try {
      await api.deleteDepartment(d.id);
      await load();
    } catch (e) {
      setToast((e as Error).message);
    }
  };

  return (
    <>
      <h1 className="page-title">部门与群</h1>
      <p className="page-sub">一个飞书群绑定一个部门：隔离记忆、日历、HITL 与默认管线</p>

      <div className="panel">
        <div className="actions" style={{ marginBottom: 12 }}>
          <button onClick={() => setFormOpen((v) => !v)}>新建部门（复制模板）</button>
        </div>
        {formOpen && (
          <div className="form-grid" style={{ marginBottom: 16 }}>
            <div className="form-row">
              <label>
                id
                <input value={form.id} onChange={(e) => setForm({ ...form, id: e.target.value })} placeholder="toutiao_2" />
              </label>
              <label>
                名称
                <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="头条图文二部" />
              </label>
              <label>
                平台
                <select value={form.platform} onChange={(e) => setForm({ ...form, platform: e.target.value })}>
                  {Object.entries(PLATFORMS).map(([k, v]) => (
                    <option value={k} key={k}>{v}</option>
                  ))}
                </select>
              </label>
            </div>
            <div>
              <span className="meta">成员（不勾 editor 即图文模板，跳过剪辑）</span>
              <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginTop: 6 }}>
                {MEMBER_OPTIONS.map((m) => (
                  <label key={m} style={{ display: "inline-flex", gap: 4 }}>
                    <input type="checkbox" checked={form.member_employee_ids.includes(m)} onChange={() => toggleMember(m)} />
                    {m}
                  </label>
                ))}
              </div>
            </div>
            <button onClick={() => void create()}>创建部门</button>
          </div>
        )}

        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>部门</th>
                <th>平台</th>
                <th>绑定群</th>
                <th>成员</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {depts.map((d) => (
                <tr key={d.id}>
                  <td>{d.name} <span className="meta">({d.id})</span></td>
                  <td>{PLATFORMS[d.platform] || d.platform}</td>
                  <td className="meta">{d.chat_id ? <code>{d.chat_id}</code> : "未绑定"}</td>
                  <td className="meta">{d.member_employee_ids.join(" / ")}</td>
                  <td>
                    <span className={`badge ${d.enabled ? "on" : "off"}`}>{d.enabled ? "启用" : "停用"}</span>
                  </td>
                  <td>
                    <button className="secondary" onClick={() => { setBindTarget(d); setBindChat(d.chat_id || ""); }}>绑定/换群</button>{" "}
                    {d.chat_id && <button className="secondary" onClick={() => void unbind(d)}>解绑</button>}{" "}
                    <button className="secondary" onClick={() => void remove(d)}>删除</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {bindTarget && (
        <div className="panel" style={{ borderColor: "var(--accent)" }}>
          <h2>绑定工作群 · {bindTarget.name}</h2>
          <p className="meta">在飞书打开/新建群 → 拉入本部门机器人 → 群内发任意消息 → 从此处选择或粘贴 chat_id。</p>
          <div className="form-row">
            <label>
              chat_id
              <select value={bindChat} onChange={(e) => setBindChat(e.target.value)}>
                <option value="">粘贴或从最近入站消息选择…</option>
                {recent.map((r) => (
                  <option value={r.chat_id} key={r.chat_id}>
                    {r.chat_id} · {r.last_text || "（最近消息）"}
                  </option>
                ))}
              </select>
            </label>
            <label>
              或手动输入
              <input value={bindChat} onChange={(e) => setBindChat(e.target.value)} placeholder="oc_xxxx" />
            </label>
          </div>
          <div className="actions" style={{ marginTop: 8 }}>
            <button onClick={() => void bind()}>保存绑定</button>
            <button className="secondary" onClick={() => setBindTarget(null)}>取消</button>
          </div>
        </div>
      )}

      {toast && <p className="meta">{toast}</p>}
    </>
  );
}
