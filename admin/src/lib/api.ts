export type LLMConfig = {
  provider: string;
  model: string;
  base_url: string;
  temperature: number;
  max_tokens: number;
};

export type ToolCapability = {
  key: string;
  name: string;
  description: string;
  enabled: boolean;
};

export type PromptSkill = {
  id: string;
  name: string;
  content: string;
  enabled: boolean;
  source?: "manual" | "upload" | "url" | "feishu";
  origin?: string;
  description?: string;
};

export type McpServer = {
  id: string;
  name: string;
  transport: "sse" | "stdio" | "http";
  url: string;
  command: string;
  args: string[];
  env: Record<string, string>;
  enabled: boolean;
  description: string;
};

export type AgentProfile = {
  role: string;
  title: string;
  identity: string;
  personality: string;
  craft: string;
  work_style: string;
  memory: string;
  capability_boundary: string;
  system_prompt: string;
  composed_system_prompt?: string;
  llm: LLMConfig;
  tools: ToolCapability[];
  skills: PromptSkill[];
  mcp_servers: McpServer[];
  enabled: boolean;
  updated_at: string;
};

export type ModelCapability = "text" | "vision" | "image" | "video" | "tts";

export type ModelProvider = {
  id: string;
  name: string;
  base_url: string;
  auth_method: "bearer" | "anthropic" | "custom_header";
  api_key_header: string;
  protocol: "openai" | "anthropic";
  timeout: number;
  builtin: boolean;
  enabled: boolean;
  api_key_masked?: string;
  has_key?: boolean;
};

export type ModelSlot = {
  id: string;
  provider_id: string;
  model_id: string;
  display_name: string;
  capability: ModelCapability[];
  context_note: string;
  price_note: string;
  enabled: boolean;
  provider_name?: string;
  provider_base_url?: string;
};

export type WorkLog = {
  log_id: string;
  date: string;
  department_id: string;
  department_name: string;
  employee_id: string;
  employee_title: string;
  project: string;
  work_type: "huddle" | "hitl" | "workflow" | "manual";
  status: "started" | "blocked" | "done" | "failed";
  summary: string;
  artifact_url: string;
  workflow_id: string;
  chat_id: string;
  stage: string;
};

export type StudioPrompt = {
  studio_voice: string;
  colleagues: string;
  updated_at: string;
};

export type PromptVersion = {
  employee_id: string;
  version: number;
  snapshot: Record<string, string>;
  note: string;
  source: string;
  created_at: string;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": "no-store",
      ...(init?.headers || {}),
    },
    ...init,
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error((await res.text()) || res.statusText);
  }
  return res.json() as Promise<T>;
}

export const api = {
  listAgents: () => request<{ items: AgentProfile[] }>("/api/admin/agents"),
  getAgent: (role: string) => request<AgentProfile>(`/api/admin/agents/${role}`),
  updateAgent: (role: string, body: Partial<AgentProfile>) =>
    request<AgentProfile>(`/api/admin/agents/${role}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  addSkill: (role: string, body: { name: string; content: string; enabled?: boolean }) =>
    request<AgentProfile>(`/api/admin/agents/${role}/skills`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  installSkill: (role: string, url: string) =>
    request<AgentProfile>(`/api/admin/agents/${role}/skills/install`, {
      method: "POST",
      body: JSON.stringify({ url }),
    }),
  uploadSkill: async (role: string, file: File) => {
    const body = new FormData();
    body.append("file", file);
    const res = await fetch(`/api/admin/agents/${role}/skills/upload`, {
      method: "POST",
      body,
      cache: "no-store",
    });
    if (!res.ok) {
      throw new Error((await res.text()) || res.statusText);
    }
    return res.json() as Promise<AgentProfile>;
  },
  updateSkill: (
    role: string,
    skillId: string,
    body: Partial<{ name: string; content: string; enabled: boolean }>,
  ) =>
    request<AgentProfile>(`/api/admin/agents/${role}/skills/${skillId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteSkill: (role: string, skillId: string) =>
    request<AgentProfile>(`/api/admin/agents/${role}/skills/${skillId}`, {
      method: "DELETE",
    }),
  addMcp: (role: string, body: Omit<McpServer, "id">) =>
    request<AgentProfile>(`/api/admin/agents/${role}/mcp`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateMcp: (role: string, mcpId: string, body: Partial<McpServer>) =>
    request<AgentProfile>(`/api/admin/agents/${role}/mcp/${mcpId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteMcp: (role: string, mcpId: string) =>
    request<AgentProfile>(`/api/admin/agents/${role}/mcp/${mcpId}`, {
      method: "DELETE",
    }),
  listMcpTools: (role: string) =>
    request<{ servers: McpServer[]; tools: Array<Record<string, string>> }>(
      `/api/admin/agents/${role}/mcp/tools`,
    ),
  resetAgents: () =>
    request<{ items: AgentProfile[] }>("/api/admin/agents/reset", { method: "POST" }),
  overview: () => request<Record<string, unknown>>("/api/admin/system/overview"),
  studioBoard: (limit = 40) =>
    request<StudioBoard>(`/api/admin/studio/board?limit=${limit}`),
  getWorkflow: (id: string) => request<Record<string, unknown>>(`/api/workflows/${id}`),
  // 模型中心
  listModelProviders: () =>
    request<{ default_provider_id: string; items: ModelProvider[] }>(
      "/api/admin/model-providers",
    ),
  createModelProvider: (body: Partial<ModelProvider> & { api_key?: string }) =>
    request<ModelProvider>("/api/admin/model-providers", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateModelProvider: (id: string, body: Partial<ModelProvider>) =>
    request<ModelProvider>(`/api/admin/model-providers/${id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteModelProvider: (id: string) =>
    request<{ ok: boolean }>(`/api/admin/model-providers/${id}`, { method: "DELETE" }),
  probeModelProvider: (id: string, body: { model_id?: string; base_url?: string } = {}) =>
    request<{ ok: boolean; latency_ms?: number; model_id?: string; error?: string }>(
      `/api/admin/model-providers/${id}/probe`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  listModelSlots: () => request<{ items: ModelSlot[] }>("/api/admin/model-slots"),
  createModelSlot: (body: Partial<ModelSlot>) =>
    request<ModelSlot>("/api/admin/model-slots", { method: "POST", body: JSON.stringify(body) }),
  updateModelSlot: (id: string, body: Partial<ModelSlot>) =>
    request<ModelSlot>(`/api/admin/model-slots/${id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteModelSlot: (id: string) =>
    request<{ ok: boolean }>(`/api/admin/model-slots/${id}`, { method: "DELETE" }),
  // Prompt OS
  getPromptStudio: () => request<StudioPrompt>("/api/admin/prompt/studio"),
  updatePromptStudio: (body: { studio_voice: string; colleagues: string }) =>
    request<StudioPrompt>("/api/admin/prompt/studio", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  listPromptVersions: (role: string) =>
    request<{ items: PromptVersion[] }>(`/api/admin/agents/${role}/prompt/versions`),
  rollbackPrompt: (role: string, version: number) =>
    request<AgentProfile>(`/api/admin/agents/${role}/prompt/rollback`, {
      method: "POST",
      body: JSON.stringify({ version }),
    }),
  // 每日工作记录
  listWorkLogs: (params: Record<string, string | number> = {}) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
    });
    return request<{ items: WorkLog[] }>(`/api/admin/work-logs?${qs.toString()}`);
  },
  createWorkLog: (body: Partial<WorkLog>) =>
    request<WorkLog>("/api/admin/work-logs", { method: "POST", body: JSON.stringify(body) }),
};

export type StudioBoard = {
  huddle: Record<string, unknown> | null;
  workflows: Array<{
    workflow_id: string;
    status: string;
    trigger?: string;
    film?: string;
    created_at?: string;
    updated_at?: string;
    error_count?: number;
    cover_count?: number;
    preview_path?: string;
    last_log?: string;
  }>;
  calendar: Array<Record<string, unknown>>;
  feishu_trace: Array<Record<string, unknown>>;
};
