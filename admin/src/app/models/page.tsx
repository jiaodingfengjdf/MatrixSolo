"use client";

import { useEffect, useState } from "react";
import { api, type ModelProvider, type ModelSlot } from "@/lib/api";

const CAPS = ["text", "vision", "image", "video", "tts"] as const;
const CAP_LABEL: Record<string, string> = {
  text: "文本",
  vision: "视觉理解",
  image: "生图",
  video: "视频",
  tts: "配音",
};

export default function ModelsPage() {
  const [providers, setProviders] = useState<ModelProvider[]>([]);
  const [slots, setSlots] = useState<ModelSlot[]>([]);
  const [providerFormOpen, setProviderFormOpen] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [slotFormOpen, setSlotFormOpen] = useState(false);
  const [form, setForm] = useState({
    id: "",
    name: "",
    base_url: "",
    auth_method: "bearer" as ModelProvider["auth_method"],
    api_key: "",
    api_key_header: "",
    protocol: "openai" as ModelProvider["protocol"],
    model_id: "",
  });
  const [slotForm, setSlotForm] = useState({
    provider_id: "",
    model_id: "",
    display_name: "",
    capability: [] as string[],
  });
  const [probe, setProbe] = useState<Record<string, string>>({});
  const [toast, setToast] = useState("");

  const refresh = async () => {
    const [p, s] = await Promise.all([api.listModelProviders(), api.listModelSlots()]);
    setProviders(p.items);
    setSlots(s.items);
  };

  useEffect(() => {
    refresh().catch((e) => setToast((e as Error).message));
  }, []);

  const saveProvider = async () => {
    if (!form.id || !form.name) return;
    try {
      if (editId) {
        await api.updateModelProvider(editId, {
          name: form.name,
          base_url: form.base_url,
          auth_method: form.auth_method,
          protocol: form.protocol,
          api_key_header: form.api_key_header,
          api_key: form.api_key || undefined,
        });
        setToast("Provider 已更新（密钥留空则不修改）。");
      } else {
        await api.createModelProvider({
          id: form.id,
          name: form.name,
          base_url: form.base_url,
          auth_method: form.auth_method,
          protocol: form.protocol,
          api_key_header: form.api_key_header,
          api_key: form.api_key,
          default_model: form.model_id,
        });
        setToast(
          form.model_id
            ? "Provider 已添加，并自动创建 text 能力槽位。"
            : "Provider 已添加，请继续在「能力槽位」填 model_id。",
        );
      }
      setProviderFormOpen(false);
      setEditId(null);
      setForm({ id: "", name: "", base_url: "", auth_method: "bearer", api_key: "", api_key_header: "", protocol: "openai", model_id: "" });
      await refresh();
    } catch (e) {
      setToast((e as Error).message);
    }
  };

  const startEditProvider = (p: ModelProvider) => {
    setEditId(p.id);
    setForm({
      id: p.id,
      name: p.name,
      base_url: p.base_url,
      auth_method: p.auth_method,
      api_key: "",
      api_key_header: p.api_key_header,
      protocol: p.protocol,
      model_id: "",
    });
    setProviderFormOpen(true);
  };

  const deleteProvider = async (p: ModelProvider) => {
    if (!confirm(`删除 Provider「${p.name}」(id=${p.id})？其模型槽位也会一并删除。`)) return;
    try {
      await api.deleteModelProvider(p.id);
      setToast("已删除 Provider。");
      await refresh();
    } catch (e) {
      setToast((e as Error).message);
    }
  };

  const toggleProvider = async (p: ModelProvider) => {
    try {
      await api.updateModelProvider(p.id, { enabled: !p.enabled });
      await refresh();
    } catch (e) {
      setToast((e as Error).message);
    }
  };

  const deleteSlot = async (s: ModelSlot) => {
    if (!confirm(`删除槽位 ${s.provider_id}/${s.model_id}？`)) return;
    try {
      await api.deleteModelSlot(s.id);
      setToast("已删除能力槽位。");
      await refresh();
    } catch (e) {
      setToast((e as Error).message);
    }
  };

  const runProbe = async (p: ModelProvider) => {
    setProbe((m) => ({ ...m, [p.id]: "探测中…" }));
    try {
      const r = await api.probeModelProvider(p.id);
      setProbe((m) => ({
        ...m,
        [p.id]: r.ok
          ? `连通 ✓ ${r.latency_ms ?? "?"}ms`
          : `失败 · ${r.error || "unknown"}`,
      }));
    } catch (e) {
      setProbe((m) => ({ ...m, [p.id]: `失败 · ${(e as Error).message}` }));
    }
  };

  const saveSlot = async () => {
    if (!slotForm.provider_id || !slotForm.model_id) return;
    try {
      await api.createModelSlot({
        provider_id: slotForm.provider_id,
        model_id: slotForm.model_id,
        display_name: slotForm.display_name,
        capability: (slotForm.capability.length ? slotForm.capability : ["text"]) as ModelSlot["capability"],
      });
      setToast("模型能力槽位已添加。");
      setSlotFormOpen(false);
      setSlotForm({ provider_id: "", model_id: "", display_name: "", capability: [] });
      await refresh();
    } catch (e) {
      setToast((e as Error).message);
    }
  };

  const toggleCap = (cap: string) => {
    setSlotForm((f) => ({
      ...f,
      capability: f.capability.includes(cap)
        ? f.capability.filter((c) => c !== cap)
        : [...f.capability, cap],
    }));
  };

  const providerById = Object.fromEntries(providers.map((p) => [p.id, p]));

  return (
    <>
      <h1 className="page-title">模型中心</h1>
      <p className="page-sub">注册 OpenAI 兼容 / Anthropic / Responses 源，按能力槽位接入，岗位/任务级路由</p>

      <div className="panel">
        <div className="actions" style={{ marginBottom: 12 }}>
          <button onClick={() => setProviderFormOpen((v) => !v)}>新增 Provider</button>
        </div>

        {providerFormOpen && (
          <div className="form-grid" style={{ marginBottom: 16 }}>
            <div className="form-row">
              <label>
                ID（slug）
                <input value={form.id} disabled={!!editId} onChange={(e) => setForm({ ...form, id: e.target.value })} placeholder="myrelay" />
              </label>
              <label>
                显示名
                <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="某某中转" />
              </label>
              <label>
                Base URL
                <input value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} placeholder="https://host/v1" />
              </label>
              {!editId && (
                <label>
                  默认模型 model_id（可选）
                  <input value={form.model_id} onChange={(e) => setForm({ ...form, model_id: e.target.value })} placeholder="deepseek-chat" />
                </label>
              )}
            </div>
            <div className="form-row">
              <label>
                鉴权
                <select
                  value={form.auth_method}
                  onChange={(e) => setForm({ ...form, auth_method: e.target.value as ModelProvider["auth_method"] })}
                >
                  <option value="bearer">Bearer</option>
                  <option value="anthropic">x-api-key</option>
                  <option value="custom_header">自定义头</option>
                </select>
              </label>
              <label>
                协议
                <select
                  value={form.protocol}
                  onChange={(e) => setForm({ ...form, protocol: e.target.value as ModelProvider["protocol"] })}
                >
                  <option value="openai">OpenAI 兼容 /chat/completions</option>
                  <option value="anthropic">Anthropic /v1/messages</option>
                  <option value="responses">Responses API (/responses)</option>
                </select>
              </label>
              <label>
                API Key
                <input type="password" value={form.api_key} onChange={(e) => setForm({ ...form, api_key: e.target.value })} placeholder="sk-…" />
              </label>
              {form.auth_method === "custom_header" && (
                <label>
                  自定义 Header 名
                  <input value={form.api_key_header} onChange={(e) => setForm({ ...form, api_key_header: e.target.value })} placeholder="x-api-key" />
                </label>
              )}
            </div>
            <div className="actions">
              <button onClick={() => void saveProvider()}>
                {editId ? "更新 Provider" : "保存 Provider"}
              </button>
              <button
                className="secondary"
                onClick={() => {
                  setProviderFormOpen(false);
                  setEditId(null);
                }}
              >
                取消
              </button>
            </div>
          </div>
        )}

        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>名称</th>
                <th>ID</th>
                <th>Base URL</th>
                <th>协议</th>
                <th>密钥</th>
                <th>状态</th>
                <th>探测</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {providers.map((p) => (
                <tr key={p.id}>
                  <td>{p.name}</td>
                  <td className="meta">{p.id}</td>
                  <td className="meta">{p.base_url || "—"}</td>
                  <td>{p.protocol}</td>
                  <td className="meta">{p.api_key_masked || "—"}</td>
                  <td>
                    <span className={`badge ${p.enabled ? "on" : "off"}`}>{p.enabled ? "启用" : "停用"}</span>
                  </td>
                  <td>
                    <button className="secondary" onClick={() => void runProbe(p)}>
                      探测
                    </button>
                    <span className="meta" style={{ marginLeft: 8, wordBreak: "break-all" }}>
                      {probe[p.id] || ""}
                    </span>
                  </td>
                  <td>
                    <button className="secondary" onClick={() => startEditProvider(p)}>编辑</button>{" "}
                    <button className="secondary" onClick={() => void toggleProvider(p)}>
                      {p.enabled ? "停用" : "启用"}
                    </button>{" "}
                    {!p.builtin && (
                      <button className="secondary" onClick={() => void deleteProvider(p)}>删除</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="panel">
        <div className="actions" style={{ marginBottom: 12 }}>
          <button onClick={() => setSlotFormOpen((v) => !v)}>新增能力槽位</button>
        </div>

        {slotFormOpen && (
          <div className="form-grid" style={{ marginBottom: 16 }}>
            <div className="form-row">
              <label>
                Provider
                <select value={slotForm.provider_id} onChange={(e) => setSlotForm({ ...slotForm, provider_id: e.target.value })}>
                  <option value="">选择…</option>
                  {providers.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
              </label>
              <label>
                model_id
                <input value={slotForm.model_id} onChange={(e) => setSlotForm({ ...slotForm, model_id: e.target.value })} placeholder="gpt-5.4" />
              </label>
              <label>
                显示名
                <input value={slotForm.display_name} onChange={(e) => setSlotForm({ ...slotForm, display_name: e.target.value })} placeholder="Grsai 文本" />
              </label>
            </div>
            <div>
              <span className="meta">能力：</span>
              {CAPS.map((c) => (
                <label key={c} style={{ display: "inline-flex", marginRight: 12, gap: 4 }}>
                  <input type="checkbox" checked={slotForm.capability.includes(c)} onChange={() => toggleCap(c)} />
                  {CAP_LABEL[c]}
                </label>
              ))}
            </div>
            <button onClick={() => void saveSlot()}>保存槽位</button>
          </div>
        )}

        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Provider</th>
                <th>model_id</th>
                <th>显示名</th>
                <th>能力槽位</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {slots.map((s) => (
                <tr key={s.id}>
                  <td>{s.provider_name || providerById[s.provider_id]?.name || s.provider_id}</td>
                  <td className="meta">{s.model_id}</td>
                  <td>{s.display_name}</td>
                  <td>{s.capability.map((c) => CAP_LABEL[c] || c).join(" / ")}</td>
                  <td>
                    <span className={`badge ${s.enabled ? "on" : "off"}`}>{s.enabled ? "启用" : "停用"}</span>
                  </td>
                  <td>
                    <button className="secondary" onClick={() => void deleteSlot(s)}>删除</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {toast && <p className="meta">{toast}</p>}
    </>
  );
}
