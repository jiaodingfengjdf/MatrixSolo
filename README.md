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
- 每岗 LLM provider/model/temperature（Provider 可选模型中心注册的自定义源）
- 每岗 MCP Server CRUD（http/sse/stdio）与工具探测
- 模型中心：自定义 Provider、连通性探测、按能力槽位（text/vision/image/video/tts）配置
- Prompt OS：L0 工作室守则可编辑、L2 分栏预览、人设版本历史与回滚
- 每日工作记录：huddle / HITL / 生产 DAG 自动落本地 `data/admin/work_logs.jsonl`，可同步飞书 `FEISHU_TABLE_WORK_LOGS`
- 配置落盘：`data/admin/agent_profiles.json`

## 升级路线（见 [PRD-后续升级.md](./PRD-后续升级.md)）

- **P0 已落地**：模型中心 / Prompt OS（L0 + 版本回滚）/ 每日工作记录 / 后台导航与总览 / Gateway 能力槽位
- P1 员工入职向导与一键润色、P2 部门与多群隔离、P3 数字人 + vision/video 为后续里程碑

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
