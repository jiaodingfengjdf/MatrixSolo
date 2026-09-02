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

## 开发者模式一键启停（测试专用）

Windows PowerShell 一键启动后端（`uvicorn --reload`）+ 管理台（`next dev`）+ 本地 MCP：

```powershell
# 一键启动
.\scripts\dev-start.bat
# 或直接双击 scripts\dev-start.bat（窗口保留，运行完按任意键关闭）

# 一键停止（会整棵进程树停止，含 --reload 子进程）
.\scripts\dev-stop.bat
```

脚本特性：自动复用项目 `.venv`（无则用全局 `python`）、端口占用时跳过避免重复启动、
日志落 `data/logs/dev_*.log`、进程记录在 `data/admin/dev_processes.json`。
可选参数（.bat）：`-SkipBackend` / `-SkipAdmin` / `-SkipMcp` / `-NoReload`（关闭热重载便于调试）/
`-Install`（启动前自动 `cd admin && npm install` 补齐依赖）。

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
- 模型中心：自定义 Provider（OpenAI 兼容 / Anthropic / Responses）、连通性探测、按能力槽位（text/vision/image/video/tts）配置
- Prompt OS：L0 工作室守则可编辑、L2 分栏预览、人设版本历史与回滚
- 每日工作记录：huddle / HITL / 生产 DAG 自动落本地 `data/admin/work_logs.jsonl`，可同步飞书 `FEISHU_TABLE_WORK_LOGS`
- 配置落盘：`data/admin/agent_profiles.json`

## 升级路线（见 [PRD-后续升级.md](./PRD-后续升级.md)）

- **P0 已落地**：模型中心 / Prompt OS（L0 + 版本回滚）/ 每日工作记录 / 后台导航与总览 / Gateway 能力槽位
- **P1 已落地**：员工动态注册表与入职向导、一键润色（七块人设草稿→编辑→保存）、WS 按注册表热重载、
  Skill 可执行闭环 + MCP stdio 最小可用、`data/admin/tool_audit.jsonl` 工具审计页
- **P2 已落地**：部门实体与预置模板（头条图文/抖音/B站）、`chat_id` 唯一绑定、部门级 huddle 成员裁剪、
  部门级工作室记忆/日历/工作记录隔离、HITL 打到部门群、无 editor 模板跳过剪辑（copy_pack 终审）
- **P3 已落地（预留 + 接口）**：数字人资产登记（声线/形象参考/口播模板，默认关）、`data/admin/digital_humans.json`、
  Gateway 能力方法 `complete_text / complete_vision / generate_image / generate_video / synthesize_speech`、
  视频异步任务（未配置 video 槽位时失败可见于工作记录）、TTS 口播样片接口；
  真实视频供应商与 vision/video 深度接入仍待决策

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
