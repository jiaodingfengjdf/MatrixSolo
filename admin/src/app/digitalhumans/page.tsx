"use client";

import { useEffect, useState } from "react";
import { api, type DigitalHuman, type Employee } from "@/lib/api";

export default function DigitalHumansPage() {
  const [assets, setAssets] = useState<DigitalHuman[]>([]);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [formOpen, setFormOpen] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [form, setForm] = useState({
    id: "",
    name: "",
    provider: "edge-tts",
    voice_id: "zh-CN-YunxiNeural",
    portrait_asset_id: "",
    portrait_path: "",
    avatar_name: "",
    opening_script: "开场三秒先抛冲突，不念标题。",
    subtitle_style: "逐字高亮，底部 8% 安全区",
    enabled: true,
  });
  const [videoForm, setVideoForm] = useState({ prompt: "", project: "" });
  const [videoResult, setVideoResult] = useState("");
  const [preview, setPreview] = useState<Record<string, string>>({});
  const [toast, setToast] = useState("");

  const load = async () => {
    const [a, e] = await Promise.all([api.listDigitalHumans(), api.listEmployees()]);
    setAssets(a.items);
    setEmployees(e.items);
  };

  useEffect(() => {
    load().catch((e) => setToast((e as Error).message));
  }, []);

  const save = async () => {
    if (!form.id || !form.name) return;
    try {
      if (editId) {
        await api.updateDigitalHuman(editId, form);
      } else {
        await api.createDigitalHuman(form);
      }
      setToast(editId ? "已更新数字人资产。" : "已登记数字人资产。");
      setFormOpen(false);
      setEditId(null);
      setForm({ ...form, id: "", name: "", portrait_asset_id: "", portrait_path: "", avatar_name: "" });
      await load();
    } catch (e) {
      setToast((e as Error).message);
    }
  };

  const startEdit = (asset: DigitalHuman) => {
    setEditId(asset.id);
    setForm({
      id: asset.id,
      name: asset.name,
      provider: asset.provider,
      voice_id: asset.voice_id,
      portrait_asset_id: asset.portrait_asset_id,
      portrait_path: asset.portrait_path,
      avatar_name: asset.avatar_name,
      opening_script: asset.opening_script,
      subtitle_style: asset.subtitle_style,
      enabled: asset.enabled,
    });
    setFormOpen(true);
  };

  const previewVoice = async (asset: DigitalHuman) => {
    setPreview((p) => ({ ...p, [asset.id]: "合成中…" }));
    try {
      const r = await api.previewDigitalHuman(asset.id, asset.opening_script || "这是口播样片。");
      setPreview((p) => ({ ...p, [asset.id]: r.ok ? `已生成 ${r.path || "(server path)"} · ${r.voice}` : `失败 ${r.error || ""}` }));
    } catch (e) {
      setPreview((p) => ({ ...p, [asset.id]: `失败 ${(e as Error).message}` }));
    }
  };

  const bindEmployee = async (assetId: string, employeeId: string) => {
    if (!employeeId) return;
    try {
      await api.updateEmployee(employeeId, {
        digital_human_id: assetId,
        digital_human_enabled: true,
        voice_id: assets.find((a) => a.id === assetId)?.voice_id || "",
      });
      setToast(`已用「${assetId}」绑定并启用员工 ${employeeId}。`);
      await load();
    } catch (e) {
      setToast((e as Error).message);
    }
  };

  const runVideo = async () => {
    if (!videoForm.prompt) return;
    try {
      const r = await api.generateVideo({
        prompt: videoForm.prompt,
        duration: 8,
        project: videoForm.project || "视频试跑",
      });
      setVideoResult(`任务 ${r.task_id} · ${r.status}（P3 供应商未实现时工作记录可见失败）`);
    } catch (e) {
      setVideoResult(`失败 ${(e as Error).message}`);
    }
  };

  return (
    <>
      <h1 className="page-title">数字人</h1>
      <p className="page-sub">
        形象层资产：声线 / 半身参考图 / 口播模板；未启用时现网静帧+TTS 不变
      </p>

      <div className="panel">
        <div className="actions" style={{ marginBottom: 12 }}>
          <button onClick={() => { setEditId(null); setFormOpen((v) => !v); }}>登记资产</button>
        </div>
        {formOpen && (
          <div className="form-grid" style={{ marginBottom: 16 }}>
            <div className="form-row">
              <label>
                id
                <input value={form.id} disabled={!!editId} onChange={(e) => setForm({ ...form, id: e.target.value })} />
              </label>
              <label>
                名称
                <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </label>
              <label>
                供应商
                <input value={form.provider} onChange={(e) => setForm({ ...form, provider: e.target.value })} />
              </label>
              <label>
                voice_id
                <input value={form.voice_id} onChange={(e) => setForm({ ...form, voice_id: e.target.value })} />
              </label>
            </div>
            <div className="form-row">
              <label>
                形象参考 asset id
                <input value={form.portrait_asset_id} onChange={(e) => setForm({ ...form, portrait_asset_id: e.target.value })} />
              </label>
              <label>
                形象路径
                <input value={form.portrait_path} onChange={(e) => setForm({ ...form, portrait_path: e.target.value })} />
              </label>
              <label>
                头像名
                <input value={form.avatar_name} onChange={(e) => setForm({ ...form, avatar_name: e.target.value })} />
              </label>
            </div>
            <label>
              开场模板
              <textarea rows={2} value={form.opening_script} onChange={(e) => setForm({ ...form, opening_script: e.target.value })} />
            </label>
            <div className="form-row">
              <label>
                字幕样式
                <input value={form.subtitle_style} onChange={(e) => setForm({ ...form, subtitle_style: e.target.value })} />
              </label>
              <label style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                <input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} />
                启用
              </label>
            </div>
            <button onClick={() => void save()}>{editId ? "更新" : "登记"}</button>
          </div>
        )}

        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>名称</th>
                <th>供应商</th>
                <th>voice</th>
                <th>形象</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {assets.map((a) => (
                <tr key={a.id}>
                  <td>{a.name} <span className="meta">({a.id})</span></td>
                  <td>{a.provider}</td>
                  <td className="meta">{a.voice_id}</td>
                  <td className="meta">{a.portrait_asset_id || a.portrait_path || "—"}</td>
                  <td>
                    <span className={`badge ${a.enabled ? "on" : "off"}`}>{a.enabled ? "启用" : "停用"}</span>
                  </td>
                  <td>
                    <button className="secondary" onClick={() => void previewVoice(a)}>口播样片</button>{" "}
                    <select defaultValue="" onChange={(e) => void bindEmployee(a.id, e.target.value)}>
                      <option value="">绑定员工…</option>
                      {employees.map((emp) => (
                        <option value={emp.id} key={emp.id}>{emp.title}</option>
                      ))}
                    </select>{" "}
                    <button className="secondary" onClick={() => startEdit(a)}>编辑</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {Object.entries(preview).map(([k, v]) => (
          <p className="meta" key={k}>{v}</p>
        ))}
      </div>

      <div className="panel">
        <h2>视频任务试跑（异步）</h2>
        <p className="meta">未配置 video 能力槽位时任务以失败写入工作记录，不阻塞 huddle/DAG。</p>
        <div className="form-row">
          <label>
            Prompt
            <input value={videoForm.prompt} onChange={(e) => setVideoForm({ ...videoForm, prompt: e.target.value })} placeholder="风雪中的电影海报，运镜缓慢" />
          </label>
          <label>
            项目名
            <input value={videoForm.project} onChange={(e) => setVideoForm({ ...videoForm, project: e.target.value })} />
          </label>
          <div style={{ alignSelf: "end" }}>
            <button onClick={() => void runVideo()}>发起视频任务</button>
          </div>
        </div>
        {videoResult && <p className="meta">{videoResult}</p>}
      </div>

      {toast && <p className="meta">{toast}</p>}
    </>
  );
}
