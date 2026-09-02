export type LLMConfig = {
  provider: "openai" | "anthropic" | "deepseek" | "grsai";
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
