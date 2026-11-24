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
