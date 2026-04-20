"""
llm_engine/vector_memory.py

Local vector-database memory for AIRPG narrative chunks.

Every piece of narrative embedded here carries a `turn_id` metadata tag.
This enables the surgical rollback required by the Checkpoint system:
when the player rewinds to turn N, all chunks with turn_id > N are
permanently deleted so they cannot bleed into the rebuilt timeline.

Backend: ChromaDB (persistent, local)
Embedding model: sentence-transformers all-MiniLM-L6-v2 (fully offline)

Collection layout
-----------------
Collection name : "narrative_memory"
Document        : the text chunk
Metadata fields : save_id (str), turn_id (int), chunk_type (str)
ID              : UUID string, generated per chunk
"""

import uuid
from typing import Any

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction


_COLLECTION_NAME: str = "narrative_memory"
_EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"


class VectorMemory:
    """Local semantic memory store backed by ChromaDB.

    Args:
        persist_dir: Filesystem path where ChromaDB will store its data.
                     Created automatically if it does not exist.
    """

    def __init__(self, persist_dir: str) -> None:
        self._persist_dir = persist_dir
        self._embedding_fn = SentenceTransformerEmbeddingFunction(
            model_name=_EMBEDDING_MODEL,
        )
        self._chroma_client = chromadb.PersistentClient(path=persist_dir)
        self._collection = self._chroma_client.get_or_create_collection(
            name=_COLLECTION_NAME,
            embedding_function=self._embedding_fn,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def embed_chunk(
        self,
        save_id: str,
        turn_id: int,
        text: str,
        chunk_type: str = "narrative",
    ) -> str:
        """Embed a text chunk and store it with turn_id metadata.

        Args:
            save_id:    The save this chunk belongs to.
            turn_id:    The narrative turn at which this chunk was produced.
            text:       The text to embed.  Must be non-empty.
            chunk_type: Category tag (e.g. "narrative", "lore", "dialogue").
                        Defaults to "narrative".

        Returns:
            The document ID (UUID string) assigned to this chunk.

        Raises:
            ValueError: If text is empty or whitespace-only.
        """
        if not text or not text.strip():
            raise ValueError("Cannot embed empty or whitespace-only text.")

        doc_id = str(uuid.uuid4())
        self._collection.add(
            documents=[text],
            metadatas=[{
                "save_id": save_id,
                "turn_id": turn_id,
                "chunk_type": chunk_type,
            }],
            ids=[doc_id],
        )
        return doc_id

    def query(
        self,
        save_id: str,
        query_text: str,
        k: int = 5,
        current_turn_id: int | None = None,
        max_turn_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve the top-k most relevant chunks using Time-Weighted search.

        Points:
        1. Semantic similarity (ChromaDB distance) is the primary signal.
        2. Recency weight: Non-lore chunks are penalized as they get older
           relative to current_turn_id.
        3. Lore immunity: Chunks with chunk_type='lore' (or turn_id=0) are
           never penalized by time.

        Args:
            save_id:         Only chunks for this save are considered.
            query_text:      The query string.
            k:               Final number of results to return.
            current_turn_id: The active turn number. If None, no time-weighting
                             is applied (only distance).
            max_turn_id:     Optional upper bound for turn_id. Chunks with
                             turn_id > max_turn_id will be excluded (unless lore).

        Returns:
            List of result dicts, sorted by final weighted score (descending).
        """
        if not query_text or not query_text.strip():
            raise ValueError("Query text must not be empty.")

        # Fetch more candidates than k to allow for re-ranking
        candidate_count = max(k * 3, 20)
        
        # Build filter condition
        where_cond: dict[str, Any] = {"save_id": save_id}
        if max_turn_id is not None:
            where_cond = {
                "$and": [
                    {"save_id": {"$eq": save_id}},
                    {"turn_id": {"$lte": max_turn_id}}
                ]
            }

        # Check available docs for this save
        all_for_save = self._collection.get(where=where_cond)
        available = len(all_for_save["ids"])
        if available == 0:
            return []
            
        fetch_k = min(candidate_count, available)

        results = self._collection.query(
            query_texts=[query_text],
            n_results=fetch_k,
            where=where_cond,
        )

        candidates: list[dict[str, Any]] = []
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for doc, meta, dist in zip(documents, metadatas, distances):
            turn_id = int(meta.get("turn_id", 0))
            chunk_type = str(meta.get("chunk_type", "narrative"))
            
            # 1. Semantic Score (0.0 to 1.0, 1.0 is perfect match)
            # ChromaDB cosine distance: 0.0 is perfect, 2.0 is opposite
            semantic_score = max(0.0, 1.0 - (float(dist) / 2.0))
            
            # 2. Recency Weight (0.1 to 1.0)
            if current_turn_id is None or chunk_type == "lore" or turn_id == 0:
                time_weight = 1.0
            else:
                # Linear decay: Lose 1% weight per turn of age, cap at 10%
                age = max(0, current_turn_id - turn_id)
                time_weight = max(0.1, 1.0 - (age * 0.01))
            
            final_score = semantic_score * time_weight
            
            candidates.append({
                "text": doc,
                "turn_id": turn_id,
                "chunk_type": chunk_type,
                "distance": float(dist),
                "score": final_score
            })

        # Sort by final score descending and take top k
        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates[:k]

    def rollback(self, save_id: str, target_turn_id: int) -> int:
        """Delete all chunks for a save with turn_id strictly greater than target.

        This is the destructive rollback required when rewinding to a previous
        checkpoint.  Chunks at or before target_turn_id are preserved.

        Args:
            save_id:        The save whose future chunks are erased.
            target_turn_id: The turn to revert to (inclusive).  All chunks
                            with turn_id > target_turn_id are deleted.

        Returns:
            The number of chunks deleted.
        """
        # ChromaDB's $gt operator requires a numeric type
        result = self._collection.get(
            where={
                "$and": [
                    {"save_id": {"$eq": save_id}},
                    {"turn_id": {"$gt": target_turn_id}},
                ]
            }
        )

        ids_to_delete: list[str] = result["ids"]
        if ids_to_delete:
            self._collection.delete(ids=ids_to_delete)

        return len(ids_to_delete)
