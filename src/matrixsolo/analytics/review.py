from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MetricInsight:
    name: str
    value: float
    owner_agent: str
    action: str


class ReviewEngine:
    """数据复盘：完播/CTR/转粉 → 归因 Agent → 自动优化建议."""

    RULES = {
        "retention_5s": (
            "文案/脚本匠",
            "优化爆款 Hook 库，重构前 3 句话情绪张力",
        ),
        "completion_rate": (
            "剪辑/后期师",
            "缩紧叙事节奏，提高切片转场频率",
        ),
        "ctr": (
            "视觉/美术师",
            "调整封面 A/B 倾向，提升饱和度与文字对比",
        ),
        "follow_rate": (
            "总编/策略官",
            "调整选题深度，强化系列化/合集心智",
        ),
    }

    def analyze(self, metrics: dict[str, float]) -> list[MetricInsight]:
        insights: list[MetricInsight] = []
        thresholds = {
            "retention_5s": 0.55,
            "completion_rate": 0.35,
            "ctr": 0.06,
            "follow_rate": 0.01,
        }
        for key, (owner, action) in self.RULES.items():
            value = float(metrics.get(key, 0))
            if value < thresholds.get(key, 0):
                insights.append(MetricInsight(key, value, owner, action))
        return insights

    def daily_report(self, metrics: dict[str, float]) -> str:
        insights = self.analyze(metrics)
        lines = ["# MatrixSolo 每日复盘", ""]
        for k, v in metrics.items():
            lines.append(f"- {k}: {v:.4f}")
        lines.append("")
        lines.append("## 优化建议")
        if not insights:
            lines.append("- 指标健康，维持当前创作基线")
        for i in insights:
            lines.append(f"- [{i.owner_agent}] {i.name}={i.value:.4f} → {i.action}")
        return "\n".join(lines)
