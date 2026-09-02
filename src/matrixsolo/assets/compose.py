from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


def ffmpeg_bin() -> str | None:
    return shutil.which("ffmpeg")


def looks_like_media(path: Path, min_bytes: int = 2000) -> bool:
    try:
        if not path.is_file() or path.stat().st_size < min_bytes:
            return False
    except OSError:
        return False
    head = path.read_bytes()[:16]
    if head.startswith(b"MatrixSolo") or head.startswith(b"MS-"):
        return False
    return True


def _escape_subtitles(path: Path) -> str:
    text = path.resolve().as_posix().replace(":", r"\:").replace("'", r"\'")
    return f"subtitles='{text}'"


async def compose_still_video(
    *,
    cover: str | Path | None,
    audio: str | Path | None,
    subtitle: str | Path | None,
    preview: str | Path,
    final: str | Path,
    duration_sec: float = 12.0,
) -> bool:
    """封面静帧 + 口播音频，拼一条可供 HITL3 预览的 mp4。"""
    import os

    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    bin_path = ffmpeg_bin()
    if not bin_path:
        return False
    cover_path = Path(cover) if cover else None
    audio_path = Path(audio) if audio else None
    preview_path = Path(preview)
    final_path = Path(final)
    if not cover_path or not looks_like_media(cover_path, min_bytes=400):
        return False
    if not audio_path or not looks_like_media(audio_path):
        return False
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    duration = max(4.0, min(float(duration_sec or 12.0), 45.0))
    vf = (
        "scale=1280:720:force_original_aspect_ratio=decrease,"
        "pad=1280:720:(ow-iw)/2:(oh-ih)/2,format=yuv420p"
    )
    sub_path = Path(subtitle) if subtitle else None
    if sub_path and sub_path.is_file() and sub_path.stat().st_size > 40:
        vf = f"{vf},{_escape_subtitles(sub_path)}"

    cmd = [
        bin_path,
        "-y",
        "-loop",
        "1",
        "-i",
        str(cover_path),
        "-i",
        str(audio_path),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-tune",
        "stillimage",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        "-t",
        f"{duration:.2f}",
        str(preview_path),
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=90)
    except (OSError, asyncio.TimeoutError) as exc:
        logger.warning("ffmpeg preview failed: %s", exc)
        return False
    if proc.returncode != 0 or not preview_path.is_file() or preview_path.stat().st_size < 1000:
        logger.warning("ffmpeg preview empty rc=%s", proc.returncode)
        return False
    try:
        shutil.copy2(preview_path, final_path)
    except OSError:
        return False
    return True
