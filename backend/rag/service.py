import logging
import threading

import chromadb
from sentence_transformers import CrossEncoder, SentenceTransformer

logger = logging.getLogger(__name__)

_MAX_WORDS_PER_CHUNK = 400
_SIMILARITY_THRESHOLD = 0.30   # skip chunks with cosine similarity < this


class RAGService:
    """ChromaDB + sentence-transformers embedding + cross-encoder reranking."""

    COLLECTION_NAME = "knowledge_base"
    EMBED_MODEL = "all-MiniLM-L6-v2"
    RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    def __init__(self, persist_dir: str):
        logger.info(f"Initialising RAGService (persist_dir={persist_dir})")
        self.client = chromadb.PersistentClient(path=persist_dir)
        self.embedder = SentenceTransformer(self.EMBED_MODEL)
        self.reranker = CrossEncoder(self.RERANK_MODEL)
        self.collection = self.client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(f"RAGService ready — collection has {self.collection.count()} chunks")

    # ── Embedding ─────────────────────────────────────────────────────────────

    def embed(self, text: str) -> list[float]:
        return self.embedder.encode(text, normalize_embeddings=True).tolist()

    # ── Chunking ──────────────────────────────────────────────────────────────

    def _chunk(self, text: str) -> list[str]:
        """Split on blank lines, keeping chunks under _MAX_WORDS_PER_CHUNK words."""
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        chunks: list[str] = []
        current: list[str] = []
        current_words = 0

        for para in paragraphs:
            words = len(para.split())
            if current_words + words > _MAX_WORDS_PER_CHUNK and current:
                chunks.append("\n\n".join(current))
                current = [para]
                current_words = words
            else:
                current.append(para)
                current_words += words

        if current:
            chunks.append("\n\n".join(current))

        return chunks

    # ── Indexing ──────────────────────────────────────────────────────────────

    def index_document(self, doc_id: str, text: str, metadata: dict) -> int:
        """Chunk, embed, and upsert a document. Returns the chunk count."""
        chunks = self._chunk(text)
        for i, chunk in enumerate(chunks):
            self.collection.upsert(
                ids=[f"{doc_id}_chunk_{i}"],
                embeddings=[self.embed(chunk)],
                documents=[chunk],
                metadatas=[{**metadata, "doc_id": doc_id, "chunk_index": i}],
            )
        logger.debug(f"Indexed doc_id={doc_id!r}: {len(chunks)} chunks")
        return len(chunks)

    # ── Search ────────────────────────────────────────────────────────────────

    def search(self, query: str, top_k: int = 10) -> list[dict]:
        """Dense vector search; filters below SIMILARITY_THRESHOLD."""
        count = self.collection.count()
        if count == 0:
            return []

        results = self.collection.query(
            query_embeddings=[self.embed(query)],
            n_results=min(top_k, count),
        )

        chunks: list[dict] = []
        for doc, dist, meta in zip(
            results["documents"][0],
            results["distances"][0],
            results["metadatas"][0],
        ):
            # hnsw:space="cosine" → distance = 1 − cosine_similarity (for unit vectors)
            similarity = 1.0 - float(dist)
            if similarity >= _SIMILARITY_THRESHOLD:
                chunks.append({
                    "content": doc,
                    "score": round(similarity, 4),
                    "source": meta.get("source", meta.get("doc_id", "unknown")),
                })

        return sorted(chunks, key=lambda x: x["score"], reverse=True)

    # ── Reranking ─────────────────────────────────────────────────────────────

    def rerank(self, query: str, chunks: list[dict], top_k: int = 5) -> list[dict]:
        """Cross-encoder reranking of candidate chunks."""
        if not chunks:
            return []

        scores = self.reranker.predict([[query, c["content"]] for c in chunks])
        ranked = sorted(zip(chunks, scores), key=lambda x: float(x[1]), reverse=True)

        return [
            {**chunk, "rerank_score": round(float(score), 4)}
            for chunk, score in ranked[:top_k]
        ]


# ── Singleton ──────────────────────────────────────────────────────────────────

_instance: RAGService | None = None
_lock = threading.Lock()


def get_rag_service(persist_dir: str = "") -> RAGService:
    global _instance
    with _lock:
        if _instance is None:
            from backend.config import settings
            _instance = RAGService(persist_dir=persist_dir or settings.chroma_persist_dir)
    return _instance
