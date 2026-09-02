export type LLMConfig = {
  provider: string;
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
  protocol: "openai" | "anthropic" | "responses";
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

export type Employee = {
  id: string;
  title: string;
  display_name: string;
  function: string;
  app_id: string;
  app_secret_masked?: string;
  has_credentials?: boolean;
  department_ids: string[];
  avatar_name: string;
  voice_id: string;
  portrait_asset_id: string;
  digital_human_id: string;
  digital_human_enabled: boolean;
  enabled: boolean;
  builtin: boolean;
  created_at: string;
  updated_at: string;
  profile?: AgentProfile;
};

export type PolishDraft = {
  employee_id: string;
  draft: Record<string, string>;
  llm_generated: boolean;
};

export type ToolAudit = {
  ts: string;
  employee_id: string;
  tool: string;
  kind: string;
  ok: boolean;
  error: string;
  duration_ms: number;
};

export type Department = {
  id: string;
  name: string;
  platform: "toutiao" | "douyin" | "bilibili" | "other";
  chat_id: string;
  hitl_chat_id: string;
  member_employee_ids: string[];
  pipeline_template: string[];
  enabled: boolean;
  created_at: string;
  updated_at: string;
};

export type RecentChat = {
  chat_id: string;
  last_text: string;
  ts: string;
};

export type DigitalHuman = {
  id: string;
  name: string;
  provider: string;
  voice_id: string;
  portrait_asset_id: string;
  portrait_path: string;
  avatar_name: string;
  opening_script: string;
  subtitle_style: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
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
  createModelProvider: (
    body: Partial<ModelProvider> & { api_key?: string; default_model?: string },
  ) =>
    request<ModelProvider>("/api/admin/model-providers", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateModelProvider: (id: string, body: Partial<ModelProvider> & { api_key?: string }) =>
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
  // 员工 / 入职 / 一键润色
  listEmployees: () => request<{ items: Employee[] }>("/api/admin/employees"),
  getEmployee: (id: string) => request<Employee>(`/api/admin/employees/${id}`),
  createEmployee: (body: Partial<Employee> & { app_secret?: string }) =>
    request<Employee>("/api/admin/employees", { method: "POST", body: JSON.stringify(body) }),
  updateEmployee: (id: string, body: Partial<Employee>) =>
    request<Employee>(`/api/admin/employees/${id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  polishEmployee: (id: string, body: { one_liner: string; department?: string; on_camera?: boolean; clone_from?: string }) =>
    request<PolishDraft>(`/api/admin/employees/${id}/polish`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  applyPolish: (id: string, draft: Record<string, string>) =>
    request<AgentProfile>(`/api/admin/employees/${id}/polish/apply`, {
      method: "POST",
      body: JSON.stringify({ draft }),
    }),
  disableEmployee: (id: string) =>
    request<Employee>(`/api/admin/employees/${id}/disable`, { method: "POST" }),
  enableEmployee: (id: string) =>
    request<Employee>(`/api/admin/employees/${id}/enable`, { method: "POST" }),
  reloadWorkers: () =>
    request<{ ok: boolean; reloaded?: boolean }>("/api/admin/workers/reload", { method: "POST" }),
  // 工具审计
  listToolAudit: (params: Record<string, string | number> = {}) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
    });
    return request<{ items: ToolAudit[] }>(`/api/admin/tool-audit?${qs.toString()}`);
  },
  // 部门与群
  listDepartments: () => request<{ items: Department[] }>("/api/admin/departments"),
  createDepartment: (body: Partial<Department>) =>
    request<Department>("/api/admin/departments", { method: "POST", body: JSON.stringify(body) }),
  updateDepartment: (id: string, body: Partial<Department>) =>
    request<Department>(`/api/admin/departments/${id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteDepartment: (id: string) =>
    request<{ ok: boolean }>(`/api/admin/departments/${id}`, { method: "DELETE" }),
  bindDepartmentChat: (id: string, chat_id: string) =>
    request<Department>(`/api/admin/departments/${id}/bind-chat`, {
      method: "POST",
      body: JSON.stringify({ chat_id }),
    }),
  unbindDepartmentChat: (id: string) =>
    request<Department>(`/api/admin/departments/${id}/unbind`, { method: "POST" }),
  recentChats: () => request<{ items: RecentChat[] }>("/api/admin/departments/recent-chats"),
  // 数字人 / 多模态网关
  listDigitalHumans: () => request<{ items: DigitalHuman[] }>("/api/admin/digital-humans"),
  createDigitalHuman: (body: Partial<DigitalHuman>) =>
    request<DigitalHuman>("/api/admin/digital-humans", { method: "POST", body: JSON.stringify(body) }),
  updateDigitalHuman: (id: string, body: Partial<DigitalHuman>) =>
    request<DigitalHuman>(`/api/admin/digital-humans/${id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteDigitalHuman: (id: string) =>
    request<{ ok: boolean }>(`/api/admin/digital-humans/${id}`, { method: "DELETE" }),
  previewDigitalHuman: (id: string, text: string) =>
    request<{ ok: boolean; path: string; voice: string; error?: string }>(
      `/api/admin/digital-humans/${id}/preview`,
      { method: "POST", body: JSON.stringify({ text }) },
    ),
  generateVideo: (body: { prompt: string; duration?: number; project?: string; workflow_id?: string }) =>
    request<{ task_id: string; status: string }>("/api/admin/gateway/video", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  generateTts: (body: { text: string; voice_id?: string }) =>
    request<{ ok: boolean; path: string; voice: string; error?: string }>("/api/admin/gateway/tts", {
      method: "POST",
      body: JSON.stringify(body),
    }),
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
