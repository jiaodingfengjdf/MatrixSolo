from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from matrixsolo.config import Settings, get_settings

logger = logging.getLogger(__name__)


class KnowledgeStore:
    """RAG 知识库：爆款文案 / 剧情事实 / 视觉 Prompt 资产.

    优先使用 Chroma；不可用时回退到本地 JSONL + 简单关键词检索。
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.settings.chroma_persist_dir.mkdir(parents=True, exist_ok=True)
        self._fallback_path = self.settings.data_dir / "rag_fallback.jsonl"
        self._collection = None
        self._use_chroma = False
        self._init_backend()

    def _init_backend(self) -> None:
        if not self.settings.chroma_enabled:
            logger.info("RAG backend: JSONL (set CHROMA_ENABLED=true to use Chroma)")
            if not self._fallback_path.exists():
                self._fallback_path.write_text("", encoding="utf-8")
            return
        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings

            client = chromadb.PersistentClient(
                path=str(self.settings.chroma_persist_dir),
                settings=ChromaSettings(anonymized_telemetry=False),
            )
            self._collection = client.get_or_create_collection(
                name=self.settings.chroma_collection,
                metadata={"hnsw:space": "cosine"},
            )
            self._use_chroma = True
            logger.info("RAG backend: Chroma (%s)", self.settings.chroma_collection)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Chroma unavailable, using JSONL fallback: %s", exc)
            self._use_chroma = False
            if not self._fallback_path.exists():
                self._fallback_path.write_text("", encoding="utf-8")

    def upsert(
        self,
        doc_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        meta = {k: ("" if v is None else str(v)) for k, v in (metadata or {}).items()}
        if self._use_chroma and self._collection is not None:
            self._collection.upsert(ids=[doc_id], documents=[text], metadatas=[meta])
            return
        record = {"id": doc_id, "text": text, "metadata": meta}
        with self._fallback_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def query(self, text: str, n_results: int = 5, where: dict[str, Any] | None = None) -> list[dict]:
        if self._use_chroma and self._collection is not None:
            kwargs: dict[str, Any] = {"query_texts": [text], "n_results": n_results}
            if where:
                kwargs["where"] = where
            try:
                result = self._collection.query(**kwargs)
            except Exception:  # noqa: BLE001
                result = self._collection.query(query_texts=[text], n_results=n_results)
            docs = result.get("documents", [[]])[0]
            metas = result.get("metadatas", [[]])[0]
            ids = result.get("ids", [[]])[0]
            dists = result.get("distances", [[]])[0]
            return [
                {
                    "id": ids[i] if i < len(ids) else "",
                    "text": docs[i],
                    "metadata": metas[i] if i < len(metas) else {},
                    "distance": dists[i] if i < len(dists) else None,
                }
                for i in range(len(docs))
            ]
        return self._fallback_query(text, n_results)

    def _fallback_query(self, text: str, n_results: int) -> list[dict]:
        if not self._fallback_path.exists():
            return []
        tokens = set(text.lower().replace("，", " ").replace("。", " ").split())
        scored: list[tuple[float, dict]] = []
        for line in self._fallback_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            doc_tokens = set(str(rec.get("text", "")).lower().split())
            score = len(tokens & doc_tokens) / max(len(tokens), 1)
            scored.append((score, rec))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {
                "id": r["id"],
                "text": r["text"],
                "metadata": r.get("metadata") or {},
                "distance": 1 - s,
            }
            for s, r in scored[:n_results]
            if s > 0
        ]

    def add_viral_sample(
        self,
        *,
        script: str,
        title: str,
        prompt: str = "",
        play_count: int = 0,
        like_ratio: float = 0.0,
    ) -> str:
        """爆款特征逆向萃取：播放破 10 万或转赞比 > 5% 自动入库."""
        if play_count < 100_000 and like_ratio <= 0.05:
            return ""
        doc_id = hashlib.md5(f"{title}|{script[:80]}".encode()).hexdigest()
        payload = f"TITLE: {title}\nSCRIPT: {script}\nPROMPT: {prompt}"
        self.upsert(
            doc_id,
            payload,
            {
                "type": "viral",
                "play_count": play_count,
                "like_ratio": like_ratio,
                "title": title,
            },
        )
        return doc_id

    def seed_defaults(self) -> None:
        samples = [
            (
                "viral_hook_001",
                "TITLE: 开场三秒决定完播\nSCRIPT: 如果你以为自己看懂了…\nPROMPT: close-up eyes",
                {"type": "viral", "form": "逐帧解说"},
            ),
            (
                "fact_inception",
                "盗梦空间 导演 克里斯托弗·诺兰 主演 莱昂纳多·迪卡普里奥 豆瓣 9.0",
                {"type": "fact", "film": "盗梦空间"},
            ),
            (
                "visual_safe_zone",
                "封面留白规则: 顶部 18% 标题安全区，人物视线朝向文字空白侧",
                {"type": "visual_rule"},
            ),
        ]
        for doc_id, text, meta in samples:
            self.upsert(doc_id, text, meta)


_store: KnowledgeStore | None = None


def get_knowledge_store() -> KnowledgeStore:
    global _store
    if _store is None:
        _store = KnowledgeStore()
        _store.seed_defaults()
    return _store
