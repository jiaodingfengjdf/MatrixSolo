from __future__ import annotations

import os
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from matrixsolo.agents.base import load_profile, require_tool
from matrixsolo.assets import AssetHub
from matrixsolo.gateway import TaskKind, get_gateway
from matrixsolo.models import CoverVariant, WorkflowState
from matrixsolo.skills.runtime import SkillRuntime, can_image_gen


class VisualAgent:
    """视觉/美术师：封面 A/B，优先走与飞书 huddle 同一套 image_gen。"""

    def __init__(self) -> None:
        self.gateway = get_gateway()
        self.assets = AssetHub()
        self.runtime = SkillRuntime()

    async def generate_covers(self, state: WorkflowState) -> WorkflowState:
        profile = load_profile("visual")
        if not profile.enabled:
            state.errors.append("视觉 Agent 已禁用")
            return state
        if not require_tool(profile, "cover_gen") and not can_image_gen(profile):
            state.log("视觉 Agent：cover_gen / image_gen 未启用，跳过")
            return state
        if not state.selected_topic or not state.script:
            state.errors.append("视觉 Agent：缺少选题或脚本")
            return state

        state.log("视觉 Agent：生成封面 A/B 测试包")
        data = await self.gateway.chat_for_role(
            "visual",
            [
                {
                    "role": "user",
                    "content": (
                        f"影片: {state.selected_topic.film_name}\n"
                        f"Hook: {state.script.hook}\n"
                        f"标题候选: {state.script.titles}\n"
                        "请输出封面 Prompt JSON。"
                    ),
                }
            ],
            kind=TaskKind.CREATIVE,
            as_json=True,
        )
        assert isinstance(data, dict)

        project = self.assets.ensure_project(state.selected_topic.film_name)
        state.film_id = self.assets.film_id(state.selected_topic.film_name)
        state.asset_dir = str(project)
        title = state.script.selected_title or (state.script.titles[0] if state.script.titles else state.selected_topic.film_name)
        film = state.selected_topic.film_name
        raw_covers = list(data.get("covers") or [])
        if not raw_covers:
            raw_covers = [
                {
                    "label": "悬疑",
                    "mood": "悬疑",
                    "prompt": (
                        f"{film} cinematic movie poster, mystery, title-safe top 18%, "
                        f"hook: {state.script.hook[:80]}"
                    ),
                },
                {
                    "label": "冲突",
                    "mood": "冲突",
                    "prompt": (
                        f"{film} high contrast poster, conflict, title-safe top 18%, "
                        f"{title}"
                    ),
                },
            ]

        covers: list[CoverVariant] = []
        live = can_image_gen(profile)
        for item in raw_covers[:3]:
            if isinstance(item, str):
                item = {"label": "cover", "mood": "", "prompt": item}
            if not isinstance(item, dict):
                continue
            variant = CoverVariant(
                label=str(item.get("label") or "cover"),
                mood=str(item.get("mood") or ""),
                prompt=str(item.get("prompt") or f"{film} cinematic poster, {title}"),
            )
            image_path: Path | None = None
            skip_live = bool(os.environ.get("PYTEST_CURRENT_TEST"))
            if live and variant.prompt.strip() and not skip_live:
                ran = await self.runtime.image_gen(variant.prompt, aspect_ratio="16:9")
                srcs = [Path(p) for p in (ran.get("paths") or []) if p]
                srcs = [p for p in srcs if p.is_file() and p.stat().st_size > 0]
                if srcs:
                    dest = project / "Covers" / f"{variant.label.replace('/', '_')}.png"
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if srcs[0].resolve() != dest.resolve():
                        shutil.copy2(srcs[0], dest)
                    else:
                        dest = srcs[0]
                    image_path = dest
                    state.log(f"视觉 Agent：{variant.label} 已真实出图")
                elif not ran.get("ok"):
                    state.log(f"视觉 Agent：{variant.label} 生图失败，改占位 — {ran.get('error')}")
            if image_path is None:
                image_path = self._render_placeholder(
                    project / "Covers",
                    variant,
                    film,
                    title,
                )
            variant.image_path = str(image_path)
            covers.append(variant)

        state.covers = covers
        state.log(f"视觉 Agent：已生成 {len(covers)} 张封面变体")
        return state

    def _render_placeholder(
        self,
        out_dir: Path,
        variant: CoverVariant,
        film_name: str,
        title: str,
    ) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{variant.label.replace('/', '_')}.png"
        moods = {
            "悬疑": (15, 40, 55),
            "冲突": (90, 25, 30),
            "情绪": (180, 120, 60),
        }
        color = (30, 60, 90)
        for key, rgb in moods.items():
            if key in variant.mood or key in variant.label:
                color = rgb
                break
        img = Image.new("RGB", (1280, 720), color)
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, 1280, 130], fill=(0, 0, 0))
        try:
            font_lg = ImageFont.truetype("arial.ttf", 42)
            font_sm = ImageFont.truetype("arial.ttf", 28)
        except OSError:
            font_lg = ImageFont.load_default()
            font_sm = font_lg
        draw.text((40, 30), title[:40], fill=(255, 255, 255), font=font_lg)
        draw.text(
            (40, 640),
            f"{film_name} · {variant.label} · {variant.mood}",
            fill=(240, 240, 240),
            font=font_sm,
        )
        img.save(path)
        return path
