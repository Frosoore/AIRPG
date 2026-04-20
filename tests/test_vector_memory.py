"""
tests/test_vector_memory.py

Unit tests for llm_engine/vector_memory.py.

ChromaDB is used with a real PersistentClient (tmp_path isolation).
The SentenceTransformerEmbeddingFunction is mocked with a fast fake that
returns random-but-consistent unit vectors, avoiding any model downloads
and making the test suite deterministic and instant.
"""

import hashlib
import math
import random
from pathlib import Path
from unittest.mock import patch
from typing import List

import pytest

import chromadb
from chromadb import EmbeddingFunction, Documents, Embeddings

from llm_engine.vector_memory import VectorMemory, _COLLECTION_NAME


# ---------------------------------------------------------------------------
# Fake embedding function — proper ChromaDB EmbeddingFunction subclass
# ---------------------------------------------------------------------------

class _FakeEmbeddingFn(EmbeddingFunction[Documents]):
    """Deterministic 32-dim unit-vector embedder for testing.

    Produces consistent vectors by hashing each input string.
    Avoids any model download; tests run instantly.
    """

    def __call__(self, input: Documents) -> Embeddings:  # noqa: A002
        embeddings: Embeddings = []
        for text in input:
            seed = int(hashlib.md5(str(text).encode()).hexdigest(), 16) % (2 ** 32)
            rng = random.Random(seed)
            vec = [rng.gauss(0, 1) for _ in range(32)]
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            embeddings.append([x / norm for x in vec])
        return embeddings


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def vm(tmp_path: Path):
    """Provide a VectorMemory instance with mocked embeddings and tmp storage."""
    with patch(
        "llm_engine.vector_memory.SentenceTransformerEmbeddingFunction",
        return_value=_FakeEmbeddingFn(),
    ):
        memory = VectorMemory(persist_dir=str(tmp_path / "chroma"))
    return memory


# ---------------------------------------------------------------------------
# embed_chunk
# ---------------------------------------------------------------------------

class TestEmbedChunk:
    def test_returns_string_id(self, vm: VectorMemory) -> None:
        doc_id = vm.embed_chunk("save1", 1, "The knight enters the dungeon.")
        assert isinstance(doc_id, str)
        assert len(doc_id) == 36  # UUID format

    def test_returns_unique_ids(self, vm: VectorMemory) -> None:
        id1 = vm.embed_chunk("save1", 1, "chunk one")
        id2 = vm.embed_chunk("save1", 2, "chunk two")
        assert id1 != id2

    def test_empty_text_raises_value_error(self, vm: VectorMemory) -> None:
        with pytest.raises(ValueError, match="empty"):
            vm.embed_chunk("save1", 1, "")

    def test_whitespace_only_raises_value_error(self, vm: VectorMemory) -> None:
        with pytest.raises(ValueError):
            vm.embed_chunk("save1", 1, "   \n  ")

    def test_chunk_retrievable_after_embed(self, vm: VectorMemory) -> None:
        vm.embed_chunk("save1", 1, "The dragon breathes fire.")
        results = vm.query("save1", "dragon fire", k=1)
        assert len(results) == 1
        assert "dragon" in results[0]["text"]

    def test_metadata_stored_correctly(self, vm: VectorMemory) -> None:
        vm.embed_chunk("save1", 5, "Important event.", chunk_type="dialogue")
        results = vm.query("save1", "important event", k=1)
        assert results[0]["turn_id"] == 5
        assert results[0]["chunk_type"] == "dialogue"

    def test_default_chunk_type_is_narrative(self, vm: VectorMemory) -> None:
        vm.embed_chunk("save1", 1, "Some narrative text.")
        results = vm.query("save1", "narrative", k=1)
        assert results[0]["chunk_type"] == "narrative"


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------

class TestQuery:
    def test_returns_empty_for_unknown_save(self, vm: VectorMemory) -> None:
        vm.embed_chunk("save1", 1, "text for save1")
        results = vm.query("save999", "text", k=5)
        assert results == []

    def test_does_not_return_other_saves_chunks(self, vm: VectorMemory) -> None:
        vm.embed_chunk("save1", 1, "secret of save one")
        vm.embed_chunk("save2", 1, "secret of save two")
        results = vm.query("save1", "secret", k=5)
        for r in results:
            # All results must belong to save1 — verify via content
            assert "save one" in r["text"]

    def test_returns_at_most_k_results(self, vm: VectorMemory) -> None:
        for i in range(10):
            vm.embed_chunk("save1", i, f"chunk number {i}")
        results = vm.query("save1", "chunk", k=3)
        assert len(results) <= 3

    def test_result_contains_required_keys(self, vm: VectorMemory) -> None:
        vm.embed_chunk("save1", 1, "the hero slays the beast")
        results = vm.query("save1", "hero", k=1)
        assert len(results) == 1
        r = results[0]
        assert "text" in r
        assert "turn_id" in r
        assert "chunk_type" in r
        assert "distance" in r

    def test_distance_is_float(self, vm: VectorMemory) -> None:
        vm.embed_chunk("save1", 1, "some text")
        results = vm.query("save1", "some text", k=1)
        assert isinstance(results[0]["distance"], float)

    def test_empty_collection_returns_empty(self, vm: VectorMemory) -> None:
        results = vm.query("save1", "anything", k=5)
        assert results == []

    def test_empty_query_text_raises(self, vm: VectorMemory) -> None:
        with pytest.raises(ValueError):
            vm.query("save1", "")

    def test_k_larger_than_available_does_not_crash(self, vm: VectorMemory) -> None:
        vm.embed_chunk("save1", 1, "only chunk")
        results = vm.query("save1", "only chunk", k=100)
        assert len(results) == 1

    def test_query_filters_by_max_turn_id(self, vm: VectorMemory) -> None:
        # Arrange: create chunks across different turns
        vm.embed_chunk("save1", 5, "Old memory")
        vm.embed_chunk("save1", 10, "Recent memory")
        vm.embed_chunk("save1", 15, "Future-ish memory")

        # Act: query with max_turn_id = 10
        # Results should only include turns 5 and 10
        results = vm.query("save1", "memory", k=10, max_turn_id=10)

        # Assert
        assert len(results) == 2
        turn_ids = {r["turn_id"] for r in results}
        assert 5 in turn_ids
        assert 10 in turn_ids
        assert 15 not in turn_ids


# ---------------------------------------------------------------------------
# rollback
# ---------------------------------------------------------------------------

class TestRollback:
    def test_deletes_chunks_after_target_turn(self, vm: VectorMemory) -> None:
        vm.embed_chunk("save1", 3, "Turn 3 event")
        vm.embed_chunk("save1", 6, "Turn 6 event")
        vm.embed_chunk("save1", 9, "Turn 9 event")

        deleted = vm.rollback("save1", target_turn_id=5)

        assert deleted == 2  # turns 6 and 9
        remaining = vm.query("save1", "event", k=10)
        assert all(r["turn_id"] <= 5 for r in remaining)

    def test_preserves_chunks_at_or_before_target(self, vm: VectorMemory) -> None:
        vm.embed_chunk("save1", 1, "Turn 1 story")
        vm.embed_chunk("save1", 5, "Turn 5 story")
        vm.embed_chunk("save1", 10, "Turn 10 story")

        vm.rollback("save1", target_turn_id=5)

        remaining = vm.query("save1", "story", k=10)
        turn_ids = {r["turn_id"] for r in remaining}
        assert 1 in turn_ids
        assert 5 in turn_ids
        assert 10 not in turn_ids

    def test_rollback_to_zero_deletes_all(self, vm: VectorMemory) -> None:
        for i in range(1, 6):
            vm.embed_chunk("save1", i, f"event at turn {i}")

        deleted = vm.rollback("save1", target_turn_id=0)

        assert deleted == 5
        assert vm.query("save1", "event", k=10) == []

    def test_rollback_does_not_affect_other_saves(self, vm: VectorMemory) -> None:
        vm.embed_chunk("save1", 10, "save1 future event")
        vm.embed_chunk("save2", 10, "save2 future event")

        vm.rollback("save1", target_turn_id=5)

        save2_results = vm.query("save2", "save2 future event", k=5)
        assert len(save2_results) == 1

    def test_rollback_beyond_all_turns_deletes_nothing(self, vm: VectorMemory) -> None:
        vm.embed_chunk("save1", 3, "event")
        deleted = vm.rollback("save1", target_turn_id=100)
        assert deleted == 0

    def test_rollback_empty_collection_returns_zero(self, vm: VectorMemory) -> None:
        deleted = vm.rollback("save1", target_turn_id=5)
        assert deleted == 0

    def test_returns_correct_count(self, vm: VectorMemory) -> None:
        for i in range(1, 8):
            vm.embed_chunk("save1", i, f"chunk {i}")

        deleted = vm.rollback("save1", target_turn_id=4)
        assert deleted == 3  # turns 5, 6, 7
