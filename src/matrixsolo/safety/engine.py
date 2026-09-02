from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from matrixsolo.gateway import TaskKind, get_gateway
from matrixsolo.rag import get_knowledge_store


# 平台限流 / 网信办常见敏感词（示例子集，可外挂词库文件扩展）
DEFAULT_SENSITIVE_MAP: dict[str, str] = {
    "杀戮": "击溃",
    "暴利": "可观收益",
    "血腥": "激烈",
    "残忍": "冷酷",
    "色情": "擦边",
    "自杀": "自我伤害",
    "赌博": "博弈",
    "吸毒": "滥用药物",
}


@dataclass
class SafetyResult:
    level: int = 0  # 0 ok / 1 降级 / 2 提示 / 3 阻断
    text: str = ""
    replacements: list[dict[str, str]] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    fact_notes: list[str] = field(default_factory=list)
    blocked: bool = False


class ContentSafetyEngine:
    """三层合规过滤：敏感词 → LLM Guardrail → 事实核查."""

    def __init__(self, sensitive_map: dict[str, str] | None = None) -> None:
        self.sensitive_map = sensitive_map or DEFAULT_SENSITIVE_MAP

    def static_filter(self, text: str) -> SafetyResult:
        result = SafetyResult(text=text, level=0)
        out = text
        for bad, good in self.sensitive_map.items():
            if bad in out:
                out = out.replace(bad, good)
                result.replacements.append({"from": bad, "to": good})
        result.text = out
        if result.replacements:
            result.level = max(result.level, 1)
            result.issues.append(f"敏感词替换 {len(result.replacements)} 处")
        return result

    async def llm_guardrail(self, text: str) -> SafetyResult:
        gateway = get_gateway()
        data = await gateway.chat_json(
            [
                {
                    "role": "system",
                    "content": (
                        "你是内容合规审查员。审查不良导向、暴力血腥描写、"
                        "违背公序良俗、未成年人保护违规。"
                        "返回 JSON: {level:0|1|2|3, pass:bool, issues:[], suggestions:[]}"
                        " level 3=高危阻断, 2=需人工复核, 1=可自动降级, 0=通过"
                    ),
                },
                {"role": "user", "content": f"请合规审查以下文案：\n{text}"},
            ],
            kind=TaskKind.GUARDRAIL,
        )
        level = int(data.get("level", 0))
        issues = [str(x) for x in data.get("issues") or []]
        return SafetyResult(
            level=level,
            text=text,
            issues=issues,
            blocked=level >= 3 or data.get("pass") is False and level >= 3,
        )

    async def fact_check(self, text: str, film_name: str | None = None) -> SafetyResult:
        store = get_knowledge_store()
        query = film_name or text[:80]
        hits = store.query(query, n_results=3)
        facts = "\n".join(h["text"] for h in hits if (h.get("metadata") or {}).get("type") == "fact")
        if not facts and hits:
            facts = "\n".join(h["text"] for h in hits[:2])

        gateway = get_gateway()
        data = await gateway.chat_json(
            [
                {
                    "role": "system",
                    "content": (
                        "你是影视事实核查员。对照已知事实，检查角色名、导演、剧情是否张冠李戴。"
                        "返回 JSON: {ok:bool, notes:[], suspicious_spans:[]}"
                    ),
                },
                {
                    "role": "user",
                    "content": f"影片: {film_name or '未知'}\n已知事实:\n{facts or '无'}\n文案:\n{text}",
                },
            ],
            kind=TaskKind.STRUCTURED,
        )
        notes = [str(x) for x in data.get("notes") or []]
        ok = bool(data.get("ok", True))
        level = 0 if ok else 2
        if data.get("suspicious_spans"):
            notes.extend(f"存疑: {s}" for s in data["suspicious_spans"])
            level = max(level, 2)
        return SafetyResult(level=level, text=text, fact_notes=notes)

    async def review(
        self,
        text: str,
        *,
        film_name: str | None = None,
        run_fact_check: bool = True,
    ) -> SafetyResult:
        layer1 = self.static_filter(text)
        layer2 = await self.llm_guardrail(layer1.text)
        merged = SafetyResult(
            text=layer1.text,
            replacements=layer1.replacements,
            issues=layer1.issues + layer2.issues,
            level=max(layer1.level, layer2.level),
            blocked=layer2.level >= 3,
        )
        if merged.blocked:
            return merged
        if run_fact_check:
            layer3 = await self.fact_check(merged.text, film_name=film_name)
            merged.fact_notes = layer3.fact_notes
            merged.level = max(merged.level, layer3.level)
            merged.issues.extend(layer3.issues)
        return merged


def highlight_spans(text: str, keywords: list[str]) -> str:
    out = text
    for kw in keywords:
        if kw:
            out = re.sub(re.escape(kw), f"**{kw}**", out)
    return out


def safety_to_dict(result: SafetyResult) -> dict[str, Any]:
    return {
        "level": result.level,
        "blocked": result.blocked,
        "replacements": result.replacements,
        "issues": result.issues,
        "fact_notes": result.fact_notes,
    }
