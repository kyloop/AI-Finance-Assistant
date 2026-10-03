from datetime import date

import httpx
import pytest

from src.kb.ingest import ingest
from src.kb.wiki import (DisambiguationPage, PageNotFound, WikiClient, WikiUnavailable, count_words, render_sections,
                         slugify, to_markdown, truncate_words)

EXTRACT = ("Lead paragraph.\n\n\n== How it works ==\nBody text here.\n\n=== Detail ===\nMore.\n\n"
           "== See also ==\nJunk.\n\n== References ==\nMore junk.")


def wiki_handler(title="Index fund", extract=EXTRACT, categories=("Category:Investing",), missing=False, calls=None):
    """Answers the three requests Wikipedia-API makes per page (info, extracts, categories) in its response shape."""
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(1)
        prop = request.url.params.get("prop")
        if missing:
            return httpx.Response(200, json={"query": {"pages": {"-1": {"ns": 0, "title": title, "missing": ""}}}})
        page = {"pageid": 1, "ns": 0, "title": title}
        if prop == "info":
            page |= {"canonicalurl": f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}", "fullurl": "x",
                     "lastrevid": 7, "length": 100, "contentmodel": "wikitext", "pagelanguage": "en"}
        elif prop == "extracts":
            page["extract"] = extract
        elif prop == "categories":
            page["categories"] = [{"ns": 14, "title": c} for c in categories]
        return httpx.Response(200, json={"query": {"pages": {"1": page}}})
    return handler


def client(handler):
    return WikiClient(delay=0, retries=2, retry_wait=0, transport=httpx.MockTransport(handler))


def test_page_text_has_markdown_headings_and_no_boilerplate_sections():
    page = client(wiki_handler()).get_page("index fund")
    assert page.text.startswith("Lead paragraph.")
    assert "## How it works" in page.text and "### Detail" in page.text
    assert "Junk" not in page.text and "References" not in page.text
    assert (page.title, page.revision_id) == ("Index fund", 7)


def test_truncate_at_paragraph_and_no_dangling_heading():
    text = "one two\n\n## Head\n\nthree four five\n\n## Tail\n\nsix seven"
    assert truncate_words(text, 6) == ("one two\n\n## Head\n\nthree four five", True)
    assert truncate_words(text, 4) == ("one two", True)                # heading not left dangling
    assert truncate_words("a b c", 10) == ("a b c", False)
    assert count_words("## Head\n\nthree four") == 3


def test_long_single_paragraph_is_cut_at_a_sentence_boundary():
    para = "First sentence has five words. Second sentence is also short. Third one ends here. " * 3
    out, cut = truncate_words(para, 12)
    assert cut and out.endswith(".") and count_words(out) <= 12 * 1.5
    assert not out.endswith("…")


def test_markdown_front_matter_and_attribution():
    page = client(wiki_handler()).get_page("Index fund")
    md = to_markdown(page, "etfs-and-mutual-funds", reviewed=date(2026, 9, 29))
    assert md.startswith('---\ntitle: "Index fund"\ncategory: "etfs-and-mutual-funds"')
    assert 'source_url: "https://en.wikipedia.org/wiki/Index_fund"' in md and "revision_id: 7" in md
    assert "CC BY-SA 4.0" in md and "last_reviewed: 2026-09-29" in md and "truncated: false" in md


def test_missing_and_disambiguation_pages():
    with pytest.raises(PageNotFound):
        client(wiki_handler(missing=True)).get_page("Nope")
    with pytest.raises(DisambiguationPage):
        client(wiki_handler(categories=("Category:All disambiguation pages",))).get_page("Mercury")


def test_retries_transient_errors_then_gives_up_and_fails_fast_on_403():
    calls = []
    inner = wiki_handler()

    def flaky(request):
        calls.append(1)
        return httpx.Response(503) if len(calls) < 3 else inner(request)

    assert client(flaky).get_page("Index fund").title == "Index fund"
    assert len(calls) > 3                                              # 2 failures were retried, then all 3 props fetched
    with pytest.raises(WikiUnavailable):
        client(lambda r: httpx.Response(503)).get_page("x")
    forbidden = []
    with pytest.raises(WikiUnavailable):
        client(lambda r: (forbidden.append(1), httpx.Response(403))[1]).get_page("x")
    assert len(forbidden) == 1


def test_ingest_writes_skips_and_reports_failures(tmp_path):
    inner, gone = wiki_handler(), wiki_handler(title="Nope", missing=True)
    handler = lambda r: gone(r) if "Nope" in str(r.url) else inner(r)  # noqa: E731
    topics = {"ETFs & mutual funds": ["Index fund", "Nope"]}
    r = ingest(client(handler), topics, tmp_path)
    assert len(r["written"]) == 1 and r["failed"][0][0] == "Nope"
    assert (tmp_path / "etfs-mutual-funds" / "index-fund.md").exists()
    assert len(ingest(client(handler), topics, tmp_path)["skipped"]) == 1
    assert ingest(client(handler), topics, tmp_path, dry_run=True)["written"][0].startswith("ETFs")


def test_render_sections_skips_dropped_section_and_its_children():
    class S:
        def __init__(self, title, text="", level=1, sections=()):
            self.title, self.text, self.level, self.sections = title, text, level, list(sections)

    out = render_sections([S("A", "a text", sections=[S("A1", "a1", 2)]), S("References", "r", sections=[S("R1", "r1", 2)])])
    assert out == "## A\n\na text\n\n### A1\n\na1"


def test_slugify():
    assert slugify("Bond (finance)") == "bond-finance" and slugify("Price–earnings ratio") == "price-earnings-ratio"
