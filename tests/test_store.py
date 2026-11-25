"""The knowledge-base store's payload indexes: Qdrant Cloud refuses a filter on an unindexed field, the local store doesn't,
so these are checked directly rather than through a search."""
from src.rag import store


class IndexRecorder:
    def __init__(self):
        self.indexes = []

    def create_payload_index(self, name, field, schema):
        self.indexes.append((name, field))


def test_the_section_lookup_has_every_field_it_filters_on_indexed(monkeypatch):
    """Topic memory re-reads a topic's sections filtering on doc_id and section; against Qdrant Cloud the missing section index
    failed every such lookup with 400 "Index required but not found"."""
    monkeypatch.setattr(store, "_indexed", set())
    client = IndexRecorder()
    store.ensure_indexes(client, "finnie_kb")
    assert {f for _, f in client.indexes} >= {"doc_id", "section"}
    store.ensure_indexes(client, "finnie_kb")                      # once per collection per process
    assert len(client.indexes) == len(store.KB_INDEXES)


def test_a_search_without_a_category_has_no_filter():
    """The tax agent's category filter once built MatchValue(None) for every other search, which failed them all."""
    from qdrant_client import models
    assert store.category_filter(None) is None
    assert isinstance(store.category_filter("bonds").must[0].match, models.MatchValue)
    assert store.category_filter(["taxes-and-accounts", "retirement"]).must[0].match.any == ["taxes-and-accounts", "retirement"]


def test_two_sections_with_the_same_heading_get_their_own_chunks():
    """'Sales taxes in the United States' has two 'History' sections; with the same id one overwrote the other in Qdrant."""
    from src.rag.chunker import chunk_document
    text = "Lead text here.\n\n## History\nFirst history.\n\n## Rates\nSome rates.\n\n## History\nSecond history."
    chunks = chunk_document("doc", "Doc", "cat", "https://x", text, max_tokens=250, split_target=200)
    assert [c.section for c in chunks] == ["(lead)", "History", "Rates", "History (2)"]
    assert len({store.point_id(c) for c in chunks}) == len(chunks)
