from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from matrixsolo.agents.base import load_profile, require_tool
from matrixsolo.assets import AssetHub
from matrixsolo.config import get_settings
from matrixsolo.models import AudioAsset, RenderResult, WorkflowState

logger = logging.getLogger(__name__)


class PostProductionAgent:
    """剪辑/后期师：TTS、字幕轴、MCP 剪辑渲染调度."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.assets = AssetHub()

    async def synthesize_audio(self, state: WorkflowState) -> WorkflowState:
        profile = load_profile("editor")
        if not profile.enabled:
            state.errors.append("剪辑 Agent 已禁用")
            return state
        if not state.script or not state.selected_topic:
            state.errors.append("剪辑 Agent：缺少脚本")
            return state

        state.log("剪辑 Agent：TTS 音频生成")
        project = Path(state.asset_dir) if state.asset_dir else self.assets.ensure_project(
            state.selected_topic.film_name
        )
        audio_dir = project / "Audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        text = f"{state.script.hook}。{state.script.body}"
        mp3_path = audio_dir / "narration.mp3"
        boundaries: list[dict] = []

        if not require_tool(profile, "tts"):
            await self._write_silent_stub(mp3_path, text)
            state.log("剪辑 Agent：tts 未启用，使用占位音频")
        else:
            try:
                if self.settings.tts_provider == "edge":
                    boundaries = await asyncio.wait_for(
                        self._edge_tts(text, mp3_path), timeout=45
                    )
                else:
                    await self._write_silent_stub(mp3_path, text)
            except Exception as exc:  # noqa: BLE001
                logger.warning("TTS failed, writing stub: %s", exc)
                await self._write_silent_stub(mp3_path, text)

        ass_path = audio_dir / "narration.ass"
        if require_tool(profile, "subtitle"):
            self._write_ass(ass_path, text, boundaries)
        else:
            ass_path.write_text("", encoding="utf-8")

        state.audio = AudioAsset(
            path=str(mp3_path),
            duration_sec=max(8.0, len(text) / 4.5),
            word_boundaries=boundaries,
            ass_subtitle_path=str(ass_path),
        )
        state.log(f"剪辑 Agent：音频与字幕已就绪 → {mp3_path.name}")
        return state

    async def _edge_tts(self, text: str, out: Path) -> list[dict]:
        import edge_tts

        communicate = edge_tts.Communicate(text, self.settings.edge_tts_voice)
        boundaries: list[dict] = []
        with out.open("wb") as fh:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    fh.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    boundaries.append(
                        {
                            "text": chunk.get("text"),
                            "offset": chunk.get("offset"),
                            "duration": chunk.get("duration"),
                        }
                    )
        return boundaries

    async def _write_silent_stub(self, out: Path, text: str) -> None:
        # 无 TTS 依赖时写占位文件
        out.write_bytes(b"ID3" + text.encode("utf-8")[:200])

    def _write_ass(self, path: Path, text: str, boundaries: list[dict]) -> None:
        header = """[Script Info]
Title: MatrixSolo
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Microsoft YaHei,48,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,2,1,2,40,40,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        lines = [header]
        if boundaries:
            for i, b in enumerate(boundaries):
                start_ms = int((b.get("offset") or 0) / 10000)
                dur_ms = int((b.get("duration") or 200_000) / 10000)
                end_ms = start_ms + max(dur_ms, 100)
                lines.append(
                    f"Dialogue: 0,{self._ms_to_ass(start_ms)},{self._ms_to_ass(end_ms)},"
                    f"Default,,0,0,0,,{b.get('text') or ''}"
                )
                if i > 80:
                    break
        else:
            # 按句粗切
            chunks = [c.strip() for c in text.replace("。", "。|").split("|") if c.strip()]
            t = 0
            for c in chunks:
                dur = max(1500, int(len(c) / 4.5 * 1000))
                lines.append(
                    f"Dialogue: 0,{self._ms_to_ass(t)},{self._ms_to_ass(t + dur)},Default,,0,0,0,,{c}"
                )
                t += dur
        path.write_text("\n".join(lines), encoding="utf-8")

    @staticmethod
    def _ms_to_ass(ms: int) -> str:
        h = ms // 3_600_000
        ms %= 3_600_000
        m = ms // 60_000
        ms %= 60_000
        s = ms // 1000
        cs = (ms % 1000) // 10
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    async def render_via_mcp(self, state: WorkflowState) -> WorkflowState:
        profile = load_profile("editor")
        if not profile.enabled:
            return state
        if not require_tool(profile, "mcp_edit"):
            state.log("剪辑 Agent：mcp_edit 未启用，跳过渲染")
            return state
        if not state.selected_topic:
            return state
        state.log("剪辑 Agent：通过 MCP 下发自动化剪辑指令")
        project = Path(state.asset_dir) if state.asset_dir else self.assets.ensure_project(
            state.selected_topic.film_name
        )
        render_dir = project / "Renders"
        render_dir.mkdir(parents=True, exist_ok=True)

        job = {
            "action": "auto_edit",
            "film": state.selected_topic.film_name,
            "audio": state.audio.path if state.audio else None,
            "subtitle": state.audio.ass_subtitle_path if state.audio else None,
            "covers": [c.image_path for c in state.covers],
            "script_hook": state.script.hook if state.script else "",
            "effects": {
                "speed_jitter": [0.98, 1.03],
                "ken_burns": True,
                "noise_opacity": 0.015,
                "edge_feather_px": 2,
            },
        }
        job_path = render_dir / "mcp_job.json"
        job_path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")

        preview = render_dir / "preview_low.mp4"
        final = project / "Export" / "final.mp4"
        final.parent.mkdir(parents=True, exist_ok=True)
        cover = next((c.image_path for c in state.covers if c.image_path), None)
        ok = await self._compose_preview(state, preview, final, cover)
        if not ok:
            ok = await self._try_mcp_render(job, preview, final)
        if not ok:
            preview.write_bytes(b"MatrixSolo-preview-stub")
            final.write_bytes(b"MatrixSolo-final-stub")
            state.log("剪辑 Agent：无 ffmpeg/MCP，写成片占位")
        rehash = self.assets.strip_and_rehash(final)
        final = Path(rehash["path"])
        md5 = rehash["md5"]

        state.render = RenderResult(
            preview_path=str(preview),
            final_path=str(final),
            compliance_score=max(0.0, 1.0 - state.safety_level * 0.15),
            compliance_report={
                "safety_level": state.safety_level,
                "issues": state.safety_messages,
                "fact_notes": state.script.fact_notes if state.script else [],
            },
            md5=md5,
        )
        state.log(f"剪辑 Agent：成片导出完成 md5={md5[:8]}…")
        return state

    async def _try_mcp_render(self, job: dict, preview: Path, final: Path) -> bool:
        try:
            import httpx

            url = f"http://{self.settings.mcp_host}:{self.settings.mcp_port}/tools/auto_edit"
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json={**job, "preview": str(preview), "final": str(final)})
                if resp.status_code == 200:
                    return True
        except Exception as exc:  # noqa: BLE001
            logger.info("MCP render unavailable, local stub used: %s", exc)
        await asyncio.sleep(0.05)
        return False

    async def _compose_preview(
        self,
        state: WorkflowState,
        preview: Path,
        final: Path,
        cover: str | None,
    ) -> bool:
        from matrixsolo.assets.compose import compose_still_video

        audio = state.audio.path if state.audio else None
        subtitle = state.audio.ass_subtitle_path if state.audio else None
        duration = state.audio.duration_sec if state.audio else 12.0
        ok = await compose_still_video(
            cover=cover,
            audio=audio,
            subtitle=subtitle,
            preview=preview,
            final=final,
            duration_sec=duration,
        )
        if ok:
            state.log("剪辑 Agent：ffmpeg 静帧口播预览已出")
        return ok
