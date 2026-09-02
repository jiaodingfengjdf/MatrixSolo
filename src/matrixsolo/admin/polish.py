from __future__ import annotations

import json
import logging
from typing import Any

from matrixsolo.admin.employees import Employee, EmployeePolishRequest
from matrixsolo.gateway import TaskKind, get_gateway

logger = logging.getLogger(__name__)

PERSONA_FIELDS = (
    "identity",
    "personality",
    "craft",
    "work_style",
    "memory",
    "capability_boundary",
    "system_prompt",
)


def default_persona_blocks(title: str, function: str = "") -> dict[str, str]:
    """新员工润色前的骨架：七块都非空，缺一不可."""
    function_cn = _function_name(function)
    return {
        "identity": (
            f"你叫{title or '新同事'}，MatrixSolo 的数字员工，职能标签 {function_cn or function or '通用'}。"
            f"群里 @{title or '我'} 就是在叫你；你以真人同事口吻工作，不是客服。"
        ),
        "personality": (
            "语气像影视工作室同事：短句、有判断、会反问、可吐槽。"
            "不自我介绍套话，不说「很高兴为你服务」，不堆 emoji，不输出 <think>。"
        ),
        "craft": (
            f"职业能力：围绕「{function_cn or function or '内容生产'}」执行具体任务，给结论再给理由，"
            "需要数据时说明口径，不编造精确数字。"
        ),
        "work_style": (
            "先交一句能用的判断，再给结构；只改被点名的段落，不整篇重写除非老板说推倒。"
            "群聊口语化，管线任务按契约输出。"
        ),
        "memory": (
            "长期记忆：MatrixSolo 是影视自媒体工作室；选题/脚本/成片终审必须老板点头，"
            "谁也无权直接全网发布；黄金槽位早7图文、午12短解说、晚18重磅长视频。"
        ),
        "capability_boundary": (
            "可做：本职能内的分析、产出与执行。\n"
            "不可做：越权拍板选题终裁、跳过 HITL 直接发布、编造事实与数据。\n"
            "越界话术：这个该找总编/文案/视觉/剪辑/运营。我只对「我的职能」负责。"
        ),
        "system_prompt": (
            "管线任务：按任务契约返回 JSON，字段名与输入要求严格一致。\n"
            "对话任务：用同事口吻直接回话，禁止输出 JSON、文件路径和客服腔。"
        ),
    }


def _function_name(function: str) -> str:
    return {
        "strategy": "总编/策略",
        "script": "文案/脚本",
        "visual": "视觉/美术",
        "editor": "剪辑/后期",
        "ops": "运营/发布",
    }.get(function, "")


async def polish_draft(
    employee: Employee,
    request: EmployeePolishRequest,
) -> dict[str, Any]:
    """一键润色：LLM 生成七块人设草稿；失败返回骨架（不报 500）。"""
    blocks = default_persona_blocks(employee.title or employee.display_name or employee.id, employee.function)
    base = json.dumps(blocks, ensure_ascii=False)
    prompt = (
        "你是 MatrixSolo 的人事系统，为数字员工生成一份专业人设草稿。\n"
        "只输出 JSON，字段必须是："
        "identity(身份:姓名/花名/@名), personality(性格:语气/口头禅), craft(职业能力), "
        "work_style(做事风格), memory(长期记忆), capability_boundary(能力边界，必须同时写可做/不可做/越界话术), "
        "system_prompt(任务契约，分「管线任务」与「对话任务」两段)。\n"
        "禁止输出 JSON 之外的任何文字。\n\n"
        f"员工：{employee.title}({employee.id})\n"
        f"职能标签：{employee.function or '通用'}\n"
        f"一句话职责：{request.one_liner or '（未提供）'}\n"
        f"所属部门：{request.department or '默认'}\n"
        f"是否出镜：{'是' if request.on_camera else '否'}\n"
        f"克隆自：{request.clone_from or '无'}\n\n"
        f"参考骨架（如生成失败则原样使用）：\n{base}"
    )
    try:
        data = await get_gateway().chat_json(
            [{"role": "user", "content": prompt}],
            kind=TaskKind.STRUCTURED,
            temperature=0.6,
            max_tokens=4096,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("polish LLM failed: %s", exc)
        data = {}
    if not isinstance(data, dict):
        data = {}
    draft = dict(blocks)
    merged = False
    for field in PERSONA_FIELDS:
        value = data.get(field)
        if isinstance(value, str) and value.strip():
            draft[field] = value.strip()
            merged = True
    # 能力边界缺「越界话术」则补骨架
    if "越界话术" not in draft["capability_boundary"]:
        draft["capability_boundary"] = blocks["capability_boundary"]
    return {"employee_id": employee.id, "draft": draft, "llm_generated": merged}
