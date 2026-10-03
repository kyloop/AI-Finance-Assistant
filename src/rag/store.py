"""Qdrant collection build and search (mds/rag-data-design.md §1-2)."""
from __future__ import annotations

import os
import threading
import uuid
import warnings
from functools import lru_cache

from qdrant_client import QdrantClient, models

from .chunker import Chunk

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384
QDRANT_LOCK = threading.RLock()     # the embedded Qdrant client isn't thread-safe: API threads and the news poller take turns
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "   # bge v1.5 retrieval instruction


@lru_cache
def get_embedder(model: str = EMBEDDING_MODEL):
    from fastembed import TextEmbedding
    return TextEmbedding(model)


def get_client(cfg: dict) -> QdrantClient:
    """Qdrant server/Cloud when `qdrant_url` is set, otherwise the local embedded store at `qdrant_path`."""
    from src.core.config import ROOT
    if cfg.get("qdrant_url"):
        return QdrantClient(url=cfg["qdrant_url"], api_key=os.getenv("QDRANT_API_KEY"))
    return QdrantClient(path=str(ROOT / cfg["qdrant_path"]))


def point_id(chunk: Chunk) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk.id))


def build_collection(client: QdrantClient, name: str, chunks: list[Chunk]) -> None:
    """(Re)create `name` and index every chunk: one point per chunk, category/doc_id payload indexes."""
    if client.collection_exists(name):
        client.delete_collection(name)
    client.create_collection(name, vectors_config=models.VectorParams(size=EMBEDDING_DIM, distance=models.Distance.COSINE))
    with warnings.catch_warnings():                   # local (embedded) Qdrant ignores payload indexes and warns
        warnings.simplefilter("ignore", UserWarning)
        for field in ("category", "doc_id"):
            client.create_payload_index(name, field, models.PayloadSchemaType.KEYWORD)
    vectors = get_embedder().embed([c.embed_text for c in chunks])
    client.upsert(name, points=[
        models.PointStruct(id=point_id(c), vector=v.tolist(), payload={
            "category": c.category, "doc_id": c.doc_id, "doc_title": c.doc_title, "section": c.section,
            "section_tokens": c.section_tokens, "piece": c.piece, "pieces": c.pieces, "tokens": c.tokens,
            "source_url": c.source_url, "text": c.text})
        for c, v in zip(chunks, vectors)])


def search(client: QdrantClient, name: str, query: str, *, k: int = 5, category: str | None = None) -> list[dict]:
    """Top-k chunks as payload dicts with a `score` (cosine similarity)."""
    qvec = next(iter(get_embedder().embed([QUERY_PREFIX + query]))).tolist()
    flt = models.Filter(must=[models.FieldCondition(key="category", match=models.MatchValue(value=category))]) if category else None
    with QDRANT_LOCK:
        hits = client.query_points(name, query=qvec, limit=k, query_filter=flt, with_payload=True).points
    return [{"score": h.score, **h.payload} for h in hits]
