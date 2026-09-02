# MatrixSolo

一人影视自媒体**多 Agent 协作中台**：飞书 HITL + **LangGraph** 编排五岗 Agent，本地/外部 **MCP** 工具接入，Next.js 管理台配置身份/提示词/Skills/LLM/MCP。

产品说明见 [`MatrixSolo.md`](./MatrixSolo.md)。后续升级规格见 [`PRD-后续升级.md`](./PRD-后续升级.md)。

## 架构

```
Next.js Admin (:3434) ──rewrite──► FastAPI (:9797)
                                      ├─ /api/admin/*  岗位配置持久化
                                      ├─ LangGraph DAG + HITL resume
                                      ├─ 五岗 Agent + LLM Gateway
                                      └─ Role MCP Runtime ──► MCP Servers
飞书五岗机器人卡片 ◄──────────────────────────────────────────┘
```

## 启动

```powershell
cd MatrixSolo
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# 后端
matrixsolo

# 本地剪辑 MCP（可选）
matrixsolo-mcp

# 管理台（另开终端）
cd admin
npm install
npm run dev
# http://127.0.0.1:3434
```

无 LLM Key 也可跑 mock：

```powershell
python -m scripts.demo_run
pytest -q
```

## 管理台能力

- 身份设定 / 能力边界 / 系统提示词
- 工具能力开关 + 提示词 Skills 增删
- 每岗 LLM provider/model/temperature
- 每岗 MCP Server CRUD（http/sse/stdio）与工具探测
- 配置落盘：`data/admin/agent_profiles.json`

## 核心 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| POST | `/api/workflows/start` | 启动工作流 |
| POST | `/api/hitl/resume` | HITL 推进 |
| GET/PUT | `/api/admin/agents` / `{role}` | 岗位配置 |
| POST/PATCH/DELETE | `/api/admin/agents/{role}/skills` | Skills |
| POST/PATCH/DELETE | `/api/admin/agents/{role}/mcp` | MCP 配置 |
| GET | `/api/admin/agents/{role}/mcp/tools` | 探测 MCP 工具 |

## 编排（LangGraph）

`ProductionOrchestrator` 使用 `StateGraph`：

`strategy → topic_HITL → script → script_HITL → visual/audio → render → final_HITL → ops`

外部飞书审批通过 `/api/hitl/resume` 从对应 entry 续跑。

## 配置

`.env` 要点：五岗 `FEISHU_*_APP_ID/SECRET`、`FEISHU_HITL_CHAT_ID`、LLM Keys。

默认 LLM 底座为 **Grsai**（OpenAI 兼容 `/v1/chat/completions`）：

```env
GRSAI_API_KEY=sk-xxx
GRSAI_BASE_URL=https://grsai.dakka.com.cn/v1
GRSAI_MODEL=gemini-3.1-pro
LLM_DEFAULT_PROVIDER=grsai
```

全球节点可将 `GRSAI_BASE_URL` 改为 `https://grsaiapi.com/v1`。
