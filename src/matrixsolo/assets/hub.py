from __future__ import annotations

import hashlib
import logging
import re
import shutil
from pathlib import Path
from typing import Any

from matrixsolo.config import Settings, get_settings

logger = logging.getLogger(__name__)


class AssetHub:
    """素材中枢：工程目录、MD5、去重与生命周期清理."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.root = self.settings.assets_dir
        self.root.mkdir(parents=True, exist_ok=True)

    def film_id(self, film_name: str) -> str:
        slug = re.sub(r"[^\w\u4e00-\u9fff]+", "_", film_name).strip("_")
        digest = hashlib.md5(film_name.encode()).hexdigest()[:8]
        return f"{digest}_{slug}"

    def ensure_project(self, film_name: str) -> Path:
        fid = self.film_id(film_name)
        base = self.root / f"{fid}"
        for sub in ("Source", "Scenes", "Audio", "Covers", "Renders", "Export", "Meta"):
            (base / sub).mkdir(parents=True, exist_ok=True)
        return base

    @staticmethod
    def file_md5(path: Path, chunk_size: int = 1024 * 1024) -> str:
        h = hashlib.md5()
        with path.open("rb") as fh:
            while True:
                chunk = fh.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()

    def strip_and_rehash(self, src: Path, dst: Path | None = None) -> dict[str, Any]:
        """元数据重置占位：复制文件并计算新 MD5（真实剥离依赖 ffmpeg）。"""
        dst = dst or src.with_name(src.stem + "_clean" + src.suffix)
        shutil.copy2(src, dst)
        # 追加无害字节扰动，改变哈希（演示防重；真实环境用 ffmpeg 重封装）
        with dst.open("ab") as fh:
            fh.write(b"\x00MATRIXSOLO")
        return {"path": str(dst), "md5": self.file_md5(dst)}

    def cleanup_cache(self, max_age_hours: int = 48) -> int:
        import time

        cache = self.settings.data_dir / "cache"
        if not cache.exists():
            return 0
        now = time.time()
        removed = 0
        for path in cache.rglob("*"):
            if path.is_file() and (now - path.stat().st_mtime) > max_age_hours * 3600:
                path.unlink(missing_ok=True)
                removed += 1
        return removed

    def index_scene_stub(self, project: Path, label: str, description: str) -> Path:
        """写入分镜语义索引占位（真实环境接入多模态 Embedding）。"""
        scene_dir = project / "Scenes"
        meta = scene_dir / f"{label}.json"
        meta.write_text(
            __import__("json").dumps(
                {"label": label, "description": description},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return meta
