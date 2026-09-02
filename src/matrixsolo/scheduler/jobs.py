from __future__ import annotations

import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from matrixsolo.assets import AssetHub
from matrixsolo.config import get_settings
from matrixsolo.orchestration import ProductionOrchestrator
from matrixsolo.rag import get_knowledge_store

logger = logging.getLogger(__name__)


def _parse_cron(expr: str) -> CronTrigger:
    # 支持标准 5 段 cron: min hour dom month dow
    parts = expr.split()
    if len(parts) != 5:
        return CronTrigger(hour=8, minute=0)
    minute, hour, day, month, day_of_week = parts
    return CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=day_of_week,
    )


class MatrixScheduler:
    """定时：热榜雷达、指标回传、缓存清理、凌晨渲染削峰占位."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.scheduler = AsyncIOScheduler()
        self.orchestrator = ProductionOrchestrator()

    def start(self) -> None:
        if not self.settings.enable_scheduler:
            logger.info("Scheduler disabled")
            return
        self.scheduler.add_job(
            self.job_hot_radar,
            _parse_cron(self.settings.hot_radar_cron),
            id="hot_radar",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.job_metrics_sync,
            _parse_cron(self.settings.metrics_sync_cron),
            id="metrics_sync",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.job_cache_cleanup,
            _parse_cron(self.settings.cache_cleanup_cron),
            id="cache_cleanup",
            replace_existing=True,
        )
        self.scheduler.start()
        logger.info("Scheduler started")

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    async def job_hot_radar(self) -> None:
        logger.info("Cron: hot radar trigger @ %s", datetime.now().isoformat())
        try:
            await self.orchestrator.start(trigger="hot_radar")
        except Exception:  # noqa: BLE001
            logger.exception("hot_radar job failed")

    async def job_metrics_sync(self) -> None:
        """每日 24:00 回传播放数据并反哺 RAG 爆款库."""
        logger.info("Cron: metrics sync")
        store = get_knowledge_store()
        # 示例：可替换为平台 Open API / RPA 回传
        samples = [
            {"title": "反转藏在第一秒", "script": "如果你以为自己看懂了", "plays": 120_000, "ratio": 0.06},
        ]
        for s in samples:
            store.add_viral_sample(
                script=s["script"],
                title=s["title"],
                play_count=s["plays"],
                like_ratio=s["ratio"],
            )

    async def job_cache_cleanup(self) -> None:
        removed = AssetHub().cleanup_cache(max_age_hours=48)
        logger.info("Cron: cache cleanup removed=%s", removed)
