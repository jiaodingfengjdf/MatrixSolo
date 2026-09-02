"use client";

import { useParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  type AgentProfile,
  type McpServer,
  type ModelProvider,
  type PromptSkill,
  type PromptVersion,
} from "@/lib/api";

type Tab = "identity" | "prompt" | "llm" | "tools" | "skills" | "mcp";

export default function AgentDetailPage() {
  const params = useParams<{ role: string }>();
  const role = params.role;
  const [agent, setAgent] = useState<AgentProfile | null>(null);
  const [tab, setTab] = useState<Tab>("identity");
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [saving, setSaving] = useState(false);
  const [versions, setVersions] = useState<PromptVersion[]>([]);
  const [modelProviders, setModelProviders] = useState<ModelProvider[]>([]);
  const [skillForm, setSkillForm] = useState({ name: "", content: "" });
  const [skillUrl, setSkillUrl] = useState("");
  const [mcpForm, setMcpForm] = useState({
    name: "",
    transport: "http" as McpServer["transport"],
    url: "http://127.0.0.1:8765",
    command: "",
    description: "",
    enabled: true,
  });
  const [mcpTools, setMcpTools] = useState<Array<Record<string, string>>>([]);
  const agentRef = useRef<AgentProfile | null>(null);
  const lastIdentityKey = useRef("");
  const lastPromptKey = useRef("");

  const identityPatch = (a: AgentProfile) => ({
    title: a.title,
    identity: a.identity,
    personality: a.personality,
    craft: a.craft,
    work_style: a.work_style,
    memory: a.memory,
    capability_boundary: a.capability_boundary,
    enabled: a.enabled,
  });

  const markSynced = (data: AgentProfile) => {
    lastIdentityKey.current = JSON.stringify(identityPatch(data));
    lastPromptKey.current = data.system_prompt;
  };

  const load = async () => {
    const data = await api.getAgent(role);
    setAgent(data);
    agentRef.current = data;
    markSynced(data);
  };

  const loadVersions = async () => {
    try {
      const r = await api.listPromptVersions(role);
      setVersions(r.items);
    } catch {
      setVersions([]);
    }
  };

  const rollback = async (version: number) => {
    try {
      const updated = await api.rollbackPrompt(role, version);
      setAgent(updated);
      agentRef.current = updated;
      markSynced(updated);
      setToast(`已回滚人设到 v${version}`);
      await loadVersions();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  useEffect(() => {
    load().catch((e: Error) => setError(e.message));
    loadVersions();
    api
      .listModelProviders()
      .then((r) => setModelProviders(r.items))
      .catch(() => setModelProviders([]));
  }, [role]);

  useEffect(() => {
    agentRef.current = agent;
  }, [agent]);

  useEffect(() => {
    const refreshIfIdle = () => {
      if (document.visibilityState && document.visibilityState !== "visible") return;
      const tag = document.activeElement?.tagName;
      if (tag === "TEXTAREA" || tag === "INPUT" || tag === "SELECT") return;
      load().catch((e: Error) => setError(e.message));
    };
    const onVis = () => {
      if (document.visibilityState === "visible") refreshIfIdle();
    };
    window.addEventListener("focus", refreshIfIdle);
    document.addEventListener("visibilitychange", onVis);
    return () => {
      window.removeEventListener("focus", refreshIfIdle);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [role]);

  const tabs = useMemo(
    () =>
      [
        ["identity", "人设与边界"],
        ["prompt", "系统提示词"],
        ["llm", "LLM"],
        ["tools", "内置技能"],
        ["skills", "技能包"],
        ["mcp", "MCP"],
      ] as const,
    [],
  );

  const save = async (patch: Partial<AgentProfile>) => {
    if (!agentRef.current) return;
    setSaving(true);
    try {
      const updated = await api.updateAgent(role, patch);
      setAgent(updated);
      agentRef.current = updated;
      markSynced(updated);
      void loadVersions();
      setToast("已同步到后端，立即生效");
      setTimeout(() => setToast(""), 2000);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const persistIdentity = () => {
    const a = agentRef.current;
    if (!a) return;
    const key = JSON.stringify(identityPatch(a));
    if (key === lastIdentityKey.current) return;
    void save(identityPatch(a));
  };

  const persistPrompt = () => {
    const a = agentRef.current;
    if (!a) return;
    if (a.system_prompt === lastPromptKey.current) return;
    void save({ system_prompt: a.system_prompt });
  };

  const applyLlm = async (nextLlm: AgentProfile["llm"]) => {
    if (!agent) return;
    setAgent({ ...agent, llm: nextLlm });
    setSaving(true);
    try {
      const updated = await api.updateAgent(role, { llm: nextLlm });
      setAgent(updated);
      setToast(`模型已生效：${nextLlm.provider}/${nextLlm.model}`);
      setTimeout(() => setToast(""), 2500);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  if (error) return <p className="error">{error}</p>;
  if (!agent) return <p className="meta">加载中…</p>;

  return (
    <>
      <h1 className="page-title">
        {agent.title} <span className="meta">/{agent.role}</span>
      </h1>
      <p className="page-sub">更新于 {new Date(agent.updated_at).toLocaleString()}</p>

      <div className="tabs">
        {tabs.map(([key, label]) => (
          <button
            key={key}
            type="button"
            className={tab === key ? "active" : ""}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "identity" && (
        <div className="panel">
          <h2>人设、能力、记忆与边界</h2>
          <p className="meta">
            与后端同一份配置。离开输入框即保存，飞书对话与工作流马上用新文案。切回页面会重新拉取。
          </p>
          <div className="form-grid">
            <label>
              标题
              <input
                value={agent.title}
                onChange={(e) => setAgent({ ...agent, title: e.target.value })}
                onBlur={persistIdentity}
              />
            </label>
            <label className="inline">
              <input
                type="checkbox"
                checked={agent.enabled}
                onChange={(e) => {
                  const next = { ...agent, enabled: e.target.checked };
                  setAgent(next);
                  agentRef.current = next;
                  void save({ ...identityPatch(next), enabled: next.enabled });
                }}
              />
              启用该岗位
            </label>
            <label>
              身份设定
              <textarea
                style={{ minHeight: 88 }}
                value={agent.identity}
                onChange={(e) => setAgent({ ...agent, identity: e.target.value })}
                onBlur={persistIdentity}
              />
            </label>
            <label>
              专属性格
              <textarea
                style={{ minHeight: 120 }}
                value={agent.personality || ""}
                onChange={(e) => setAgent({ ...agent, personality: e.target.value })}
                onBlur={persistIdentity}
              />
            </label>
            <label>
              专属职业能力
              <textarea
                style={{ minHeight: 120 }}
                value={agent.craft || ""}
                onChange={(e) => setAgent({ ...agent, craft: e.target.value })}
                onBlur={persistIdentity}
              />
            </label>
            <label>
              专属做事风格
              <textarea
                style={{ minHeight: 120 }}
                value={agent.work_style || ""}
                onChange={(e) => setAgent({ ...agent, work_style: e.target.value })}
                onBlur={persistIdentity}
              />
            </label>
            <label>
              专属记忆
              <textarea
                style={{ minHeight: 140 }}
                value={agent.memory || ""}
                onChange={(e) => setAgent({ ...agent, memory: e.target.value })}
                onBlur={persistIdentity}
              />
            </label>
            <label>
              能力边界
              <textarea
                style={{ minHeight: 120 }}
                value={agent.capability_boundary}
                onChange={(e) =>
                  setAgent({ ...agent, capability_boundary: e.target.value })
                }
                onBlur={persistIdentity}
              />
            </label>
          </div>
          <div className="actions">
            <button type="button" disabled={saving} onClick={persistIdentity}>
              保存到后端
            </button>
            <button
              type="button"
              className="secondary"
              disabled={saving}
              onClick={() => load().catch((e: Error) => setError(e.message))}
            >
              从后端刷新
            </button>
          </div>

          <div style={{ marginTop: 16 }}>
            <h3>人设版本历史</h3>
            <p className="meta" style={{ marginTop: 4 }}>
              每次保存身份字段自动登记一版；润色与回滚也会追加版本。可回滚到任意历史版本。
            </p>
            {versions.length === 0 ? (
              <p className="meta">暂无版本记录。</p>
            ) : (
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th>版本</th>
                      <th>来源</th>
                      <th>时间</th>
                      <th>备注</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...versions].reverse().map((v) => (
                      <tr key={v.version}>
                        <td>v{v.version}</td>
                        <td className="meta">{v.source}</td>
                        <td className="meta">{v.created_at.slice(0, 19).replace("T", " ")}</td>
                        <td className="meta">{v.note || "—"}</td>
                        <td>
                          <button className="secondary" onClick={() => void rollback(v.version)}>
                            回滚
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {tab === "prompt" && (
        <div className="panel">
          <h2>系统级提示词</h2>
          <p className="meta">
            任务契约与后端同一字段。离开输入框即保存。下方只读区是模型实际吃到的完整 system（含人设与边界）。
          </p>
          <label>
            System Prompt
            <textarea
              style={{ minHeight: 220 }}
              value={agent.system_prompt}
              onChange={(e) => setAgent({ ...agent, system_prompt: e.target.value })}
              onBlur={persistPrompt}
            />
          </label>
          <label>
            后端实际注入的完整提示词（只读）
            <textarea
              readOnly
              style={{ minHeight: 260, opacity: 0.85 }}
              value={agent.composed_system_prompt || ""}
            />
          </label>
          <div className="actions">
            <button type="button" disabled={saving} onClick={persistPrompt}>
              保存到后端
            </button>
            <button
              type="button"
              className="secondary"
              disabled={saving}
              onClick={() => load().catch((e: Error) => setError(e.message))}
            >
              从后端刷新
            </button>
          </div>
        </div>
      )}

      {tab === "llm" && (
        <div className="panel">
          <h2>LLM 接入</h2>
          <p className="meta">修改后自动保存，下一轮 Agent 调用立即使用新模型</p>
          <div className="form-row">
            <label>
              Provider
              <select
                value={agent.llm.provider}
                disabled={saving}
                onChange={(e) => {
                  const provider = e.target.value;
                  const presets: Record<string, { model: string; base_url: string }> = {
                    grsai: {
                      model: "gpt-5.4",
                      base_url: "https://grsai.dakka.com.cn/v1",
                    },
                    openai: { model: "gpt-4o", base_url: "https://api.openai.com/v1" },
                    anthropic: {
                      model: "claude-3-5-sonnet-20241022",
                      base_url: "https://api.anthropic.com",
                    },
                    deepseek: {
                      model: "deepseek-chat",
                      base_url: "https://api.deepseek.com",
                    },
                  };
                  const preset = presets[provider];
                  const custom = modelProviders.find((p) => p.id === provider && !p.builtin);
                  void applyLlm({
                    ...agent.llm,
                    provider,
                    model: preset?.model || agent.llm.model,
                    base_url: preset?.base_url || custom?.base_url || agent.llm.base_url,
                  });
                }}
              >
                <option value="grsai">grsai（推荐）</option>
                <option value="openai">openai</option>
                <option value="anthropic">anthropic</option>
                <option value="deepseek">deepseek</option>
                {modelProviders
                  .filter((p) => !p.builtin)
                  .map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name || p.id}（自定义）
                    </option>
                  ))}
              </select>
            </label>
            <label>
              Model
              <input
                value={agent.llm.model}
                disabled={saving}
                onChange={(e) =>
                  setAgent({ ...agent, llm: { ...agent.llm, model: e.target.value } })
                }
                onBlur={(e) =>
                  void applyLlm({ ...agent.llm, model: e.target.value.trim() })
                }
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.currentTarget.blur();
                  }
                }}
              />
            </label>
            <label>
              Temperature
              <input
                type="number"
                step="0.1"
                value={agent.llm.temperature}
                disabled={saving}
                onChange={(e) =>
                  setAgent({
                    ...agent,
                    llm: { ...agent.llm, temperature: Number(e.target.value) },
                  })
                }
                onBlur={(e) =>
                  void applyLlm({
                    ...agent.llm,
                    temperature: Number(e.target.value),
                  })
                }
              />
            </label>
            <label>
              Max Tokens
              <input
                type="number"
                value={agent.llm.max_tokens}
                disabled={saving}
                onChange={(e) =>
                  setAgent({
                    ...agent,
                    llm: { ...agent.llm, max_tokens: Number(e.target.value) },
                  })
                }
                onBlur={(e) =>
                  void applyLlm({
                    ...agent.llm,
                    max_tokens: Number(e.target.value),
                  })
                }
              />
            </label>
          </div>
          <label>
            Base URL（可选覆盖）
            <input
              value={agent.llm.base_url}
              disabled={saving}
              onChange={(e) =>
                setAgent({ ...agent, llm: { ...agent.llm, base_url: e.target.value } })
              }
              onBlur={(e) =>
                void applyLlm({ ...agent.llm, base_url: e.target.value.trim() })
              }
            />
          </label>
          <div className="actions">
            <button
              type="button"
              disabled={saving}
              onClick={() => void applyLlm(agent.llm)}
            >
              {saving ? "保存中…" : "立即生效"}
            </button>
          </div>
        </div>
      )}

      {tab === "tools" && (
        <div className="panel">
          <h2>内置技能</h2>
          <p className="meta">
            开关即技能。关闭后该岗不能联网、爬虫、拉热榜或生图。修改后立即保存。
          </p>
          {agent.tools.map((t, idx) => (
            <div className="item" key={t.key}>
              <div>
                <strong>{t.name}</strong>
                <p className="meta">
                  {t.key} · {t.description}
                </p>
              </div>
              <label className="inline">
                <input
                  type="checkbox"
                  checked={t.enabled}
                  disabled={saving}
                  onChange={(e) => {
                    const tools = [...agent.tools];
                    tools[idx] = { ...t, enabled: e.target.checked };
                    setAgent({ ...agent, tools });
                    void save({ tools });
                  }}
                />
                启用
              </label>
            </div>
          ))}
        </div>
      )}

      {tab === "skills" && (
        <div className="panel">
          <h2>技能包</h2>
          <p className="meta">
            上传 SKILL.md / zip，或粘贴地址安装。飞书里把同样的地址发给被 @ 的岗位也会学会。
          </p>
          <div className="form-grid">
            <label>
              技能地址
              <input
                placeholder="https://…/SKILL.md 或 zip"
                value={skillUrl}
                onChange={(e) => setSkillUrl(e.target.value)}
              />
            </label>
            <label>
              上传技能包
              <input
                type="file"
                accept=".md,.markdown,.zip,.txt"
                onChange={async (e) => {
                  const file = e.target.files?.[0];
                  e.target.value = "";
                  if (!file) return;
                  try {
                    const updated = await api.uploadSkill(role, file);
                    setAgent(updated);
                    setToast(`已安装《${file.name}》`);
                  } catch (err) {
                    setError((err as Error).message);
                  }
                }}
              />
            </label>
          </div>
          <div className="actions">
            <button
              type="button"
              disabled={saving || !skillUrl.trim()}
              onClick={async () => {
                try {
                  const updated = await api.installSkill(role, skillUrl.trim());
                  setAgent(updated);
                  setSkillUrl("");
                  setToast("技能包已安装");
                } catch (err) {
                  setError((err as Error).message);
                }
              }}
            >
              从 URL 安装
            </button>
          </div>
          {agent.skills.map((s: PromptSkill) => (
            <div className="item" key={s.id}>
              <div>
                <strong>{s.name}</strong>
                <p className="meta">
                  {(s.source || "manual") + (s.origin ? ` · ${s.origin}` : "")}
                </p>
                <pre className="meta" style={{ whiteSpace: "pre-wrap" }}>
                  {(s.description || s.content).slice(0, 280)}
                </pre>
                <label className="inline">
                  <input
                    type="checkbox"
                    checked={s.enabled}
                    onChange={async (e) => {
                      const updated = await api.updateSkill(role, s.id, {
                        enabled: e.target.checked,
                      });
                      setAgent(updated);
                    }}
                  />
                  启用
                </label>
              </div>
              <button
                type="button"
                className="danger"
                onClick={async () => {
                  const updated = await api.deleteSkill(role, s.id);
                  setAgent(updated);
                  setToast("技能包已删除");
                }}
              >
                删除
              </button>
            </div>
          ))}
          <h2>高级：手动添加说明书</h2>
          <div className="form-grid">
            <label>
              名称
              <input
                value={skillForm.name}
                onChange={(e) => setSkillForm({ ...skillForm, name: e.target.value })}
              />
            </label>
            <label>
              内容
              <textarea
                value={skillForm.content}
                onChange={(e) => setSkillForm({ ...skillForm, content: e.target.value })}
              />
            </label>
          </div>
          <div className="actions">
            <button
              type="button"
              onClick={async () => {
                if (!skillForm.name.trim()) return;
                const updated = await api.addSkill(role, skillForm);
                setAgent(updated);
                setSkillForm({ name: "", content: "" });
                setToast("Skill 已添加");
              }}
            >
              添加
            </button>
          </div>
        </div>
      )}

      {tab === "mcp" && (
        <div className="panel">
          <h2>MCP Server 接入</h2>
          {(agent.mcp_servers || []).map((m) => (
            <div className="item" key={m.id}>
              <div>
                <strong>{m.name}</strong>
                <p className="meta">
                  {m.transport} · {m.url || m.command} · {m.description}
                </p>
                <label className="inline">
                  <input
                    type="checkbox"
                    checked={m.enabled}
                    onChange={async (e) => {
                      const updated = await api.updateMcp(role, m.id, {
                        enabled: e.target.checked,
                      });
                      setAgent(updated);
                    }}
                  />
                  启用
                </label>
              </div>
              <button
                type="button"
                className="danger"
                onClick={async () => {
                  const updated = await api.deleteMcp(role, m.id);
                  setAgent(updated);
                  setToast("MCP 已删除");
                }}
              >
                删除
              </button>
            </div>
          ))}

          <div className="actions">
            <button
              type="button"
              className="secondary"
              onClick={async () => {
                const data = await api.listMcpTools(role);
                setMcpTools(data.tools);
                setToast(`探测到 ${data.tools.length} 个工具`);
              }}
            >
              探测已启用 MCP 工具
            </button>
          </div>
          {mcpTools.length > 0 && (
            <div style={{ marginTop: 12 }}>
              {mcpTools.map((t, i) => (
                <p className="meta" key={`${t.name}-${i}`}>
                  {t.server_name}/{t.name} — {t.description || t.error || ""}
                </p>
              ))}
            </div>
          )}

          <h2 style={{ marginTop: 20 }}>新增 MCP</h2>
          <div className="form-row">
            <label>
              名称
              <input
                value={mcpForm.name}
                onChange={(e) => setMcpForm({ ...mcpForm, name: e.target.value })}
              />
            </label>
            <label>
              Transport
              <select
                value={mcpForm.transport}
                onChange={(e) =>
                  setMcpForm({
                    ...mcpForm,
                    transport: e.target.value as McpServer["transport"],
                  })
                }
              >
                <option value="http">http</option>
                <option value="sse">sse</option>
                <option value="stdio">stdio</option>
              </select>
            </label>
            <label>
              URL
              <input
                value={mcpForm.url}
                onChange={(e) => setMcpForm({ ...mcpForm, url: e.target.value })}
              />
            </label>
            <label>
              Command（stdio）
              <input
                value={mcpForm.command}
                onChange={(e) => setMcpForm({ ...mcpForm, command: e.target.value })}
              />
            </label>
          </div>
          <label>
            描述
            <input
              value={mcpForm.description}
              onChange={(e) => setMcpForm({ ...mcpForm, description: e.target.value })}
            />
          </label>
          <div className="actions">
            <button
              type="button"
              onClick={async () => {
                if (!mcpForm.name.trim()) return;
                const updated = await api.addMcp(role, {
                  ...mcpForm,
                  args: [],
                  env: {},
                });
                setAgent(updated);
                setMcpForm({
                  name: "",
                  transport: "http",
                  url: "http://127.0.0.1:8765",
                  command: "",
                  description: "",
                  enabled: true,
                });
                setToast("MCP 已添加");
              }}
            >
              添加 MCP
            </button>
          </div>
        </div>
      )}

      {toast ? <div className="toast">{toast}</div> : null}
    </>
  );
}
