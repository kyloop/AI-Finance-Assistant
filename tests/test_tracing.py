from src.core import tracing
from src.workflow.graph import _run_config


def test_tracing_off_without_keys():
    assert not tracing.tracing_enabled()
    assert tracing.run_callbacks() == []


def test_tracing_on_with_keys(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    assert tracing.tracing_enabled()


def test_run_config_hashes_session_id():
    cfg = _run_config(db=None, trace={"session_id": "abc123", "conversation_id": 7})
    assert cfg["callbacks"] == [] and cfg["recursion_limit"] == 60
    sid = cfg["metadata"]["langfuse_session_id"]
    assert sid != "abc123" and "abc123" not in sid and len(sid) == 16
    assert sid == tracing.session_hash("abc123")               # same session, same Langfuse group
    assert cfg["metadata"]["conversation_id"] == "7"


def test_mask_blanks_personal_fields_at_any_depth():
    state = {"question": "How is my portfolio doing?", "holdings": [{"symbol": "AAPL", "shares": 10}],
             "profile": {"risk": "high"}, "history": [{"role": "user", "content": "hi"}],
             "nested": {"saved_goal": {"target": 50000}, "items": [{"profile": {"age": 40}}]}}
    out = tracing.mask(data=state)
    assert out["question"] == "How is my portfolio doing?"
    assert out["holdings"] == out["profile"] == out["history"] == "<masked>"
    assert out["nested"]["saved_goal"] == "<masked>"
    assert out["nested"]["items"][0]["profile"] == "<masked>"
    assert state["holdings"][0]["symbol"] == "AAPL"              # the app's own data is untouched
