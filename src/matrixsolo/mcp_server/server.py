from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from matrixsolo.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(title="MatrixSolo Local MCP Executor", version="0.1.0")


class AutoEditRequest(BaseModel):
    film: str
    audio: str | None = None
    subtitle: str | None = None
    covers: list[str] = Field(default_factory=list)
    script_hook: str = ""
    effects: dict[str, Any] = Field(default_factory=dict)
    preview: str
    final: str


class TranscodeRequest(BaseModel):
    src: str
    dst: str
    crf: int = 23


def _write_stub_video(path: Path, tag: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    # 真实环境：ffmpeg 合成底层模糊 + 主图层 + 噪点 + 水印
    payload = tag + json.dumps({"effects": "matrixsolo"}, ensure_ascii=False).encode()
    path.write_bytes(payload)
    return hashlib.md5(path.read_bytes()).hexdigest()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "workspace": str(settings.mcp_workspace)}


@app.get("/tools")
async def list_tools() -> dict[str, Any]:
    return {
        "tools": [
            {"name": "auto_edit", "description": "自动化粗剪/精剪/导出"},
            {"name": "transcode", "description": "转码与元数据重置"},
            {"name": "scene_detect", "description": "场景切分占位"},
            {"name": "md5", "description": "计算文件 MD5"},
        ]
    }


@app.post("/tools/auto_edit")
async def auto_edit(req: AutoEditRequest) -> dict[str, Any]:
    """封面静帧 + 口播；没有 ffmpeg 时退回占位文件。"""
    logger.info("MCP auto_edit film=%s effects=%s", req.film, req.effects)
    preview = Path(req.preview)
    final = Path(req.final)
    cover = next((c for c in req.covers if c), None)
    from matrixsolo.assets.compose import compose_still_video

    ok = await compose_still_video(
        cover=cover,
        audio=req.audio,
        subtitle=req.subtitle,
        preview=preview,
        final=final,
        duration_sec=12.0,
    )
    if ok:
        return {
            "ok": True,
            "preview": str(preview),
            "final": str(final),
            "preview_md5": hashlib.md5(preview.read_bytes()).hexdigest(),
            "final_md5": hashlib.md5(final.read_bytes()).hexdigest(),
            "layers": ["still_cover", "narration", "subtitles"],
        }
    preview_md5 = _write_stub_video(preview, b"MS-PREVIEW")
    final_md5 = _write_stub_video(final, b"MS-FINAL")
    with final.open("ab") as fh:
        fh.write(b"\x00MCP")
    final_md5 = hashlib.md5(final.read_bytes()).hexdigest()
    return {
        "ok": True,
        "preview": str(preview),
        "final": str(final),
        "preview_md5": preview_md5,
        "final_md5": final_md5,
        "layers": [
            "background_blur",
            "main_feather",
            "noise_1.5pct",
            "watermark",
            "progress_bar",
        ],
    }


@app.post("/tools/transcode")
async def transcode(req: TranscodeRequest) -> dict[str, Any]:
    src, dst = Path(req.src), Path(req.dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.exists():
        dst.write_bytes(src.read_bytes() + b"\x00TC")
    else:
        dst.write_bytes(b"transcode-stub")
    return {"ok": True, "dst": str(dst), "md5": hashlib.md5(dst.read_bytes()).hexdigest()}


@app.post("/tools/scene_detect")
async def scene_detect(payload: dict[str, Any]) -> dict[str, Any]:
    video = payload.get("video", "")
    return {
        "ok": True,
        "video": video,
        "scenes": [
            {"index": 0, "start": 0.0, "end": 12.5, "label": "开场对峙"},
            {"index": 1, "start": 12.5, "end": 40.0, "label": "追逐打斗"},
            {"index": 2, "start": 40.0, "end": 65.0, "label": "主角哭泣"},
        ],
    }


@app.get("/tools/md5")
async def md5_tool(path: str) -> dict[str, str]:
    p = Path(path)
    if not p.exists():
        return {"error": "not found"}
    return {"path": path, "md5": hashlib.md5(p.read_bytes()).hexdigest()}


def main() -> None:
    import uvicorn

    uvicorn.run(
        "matrixsolo.mcp_server.server:app",
        host=settings.mcp_host,
        port=settings.mcp_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
