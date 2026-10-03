"""Q&A and tax agents answer from the knowledge base first, falling back to Wikipedia (conftest stubs both)."""
from src.core.config import DISCLAIMER, get_config
from src.workflow.graph import run_chat
from src.workflow.tools import set_kb_searcher

PROFILE = {"knowledge_level": "beginner", "risk_tolerance": "moderate"}
MIN = get_config()["rag"]["min_score"]


def hit(score, *, section="Compounding frequency", text="The compounding frequency is the number of times per year interest is added."):
    return {"score": score, "doc_id": "compound-interest", "doc_title": "Compound interest", "section": section,
            "text": text, "source_url": "https://en.wikipedia.org/wiki/Compound_interest", "category": "basics",
            "piece": 0, "pieces": 1, "tokens": 30, "section_tokens": 30}


def ask(q):
    return run_chat(q, history=[], profile=PROFILE, holdings=[], db=None)


def test_strong_match_answers_from_knowledge_base_with_section_citations():
    set_kb_searcher(lambda q, k=None: [hit(MIN + 0.1), hit(MIN + 0.05), hit(MIN + 0.02, section="(lead)", text="Compound interest is interest on interest.")])
    s = ask("How often can interest be added to my savings?")
    assert "number of times per year" in s["final_response"] and s["final_response"].endswith(DISCLAIMER)
    assert [src["url"] for src in s["sources"]] == ["https://en.wikipedia.org/wiki/Compound_interest#Compounding_frequency",
                                                    "https://en.wikipedia.org/wiki/Compound_interest"]   # one per section
    assert any(t.startswith("kb_search → 3 chunks") for t in s["trace"])
    assert not any("wiki_search" in t for t in s["trace"])


def test_weak_match_falls_back_to_wikipedia():
    set_kb_searcher(lambda q, k=None: [hit(MIN - 0.05)])
    s = ask("What is an ETF?")
    assert any("wiki_search('ETF')" in t for t in s["trace"])
    assert s["sources"][0]["url"] == "https://en.wikipedia.org/wiki/Exchange-traded_fund"


def test_broken_index_falls_back_to_wikipedia():
    def boom(q, k=None):
        raise RuntimeError("qdrant unavailable")
    set_kb_searcher(boom)
    s = ask("What is an ETF?")
    assert s["agents"] == ["Finance Q&A"] and any("wiki_search('ETF')" in t for t in s["trace"])
