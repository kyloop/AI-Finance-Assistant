# RAG data design: storage hierarchy and chunking

Decision record for how Finnie's knowledge base is stored in the vector database and cut into chunks.
The measurements behind these numbers are in [kb-token-stats-basics.md](kb-token-stats-basics.md).

| | |
|---|---|
| Status | Decided: hierarchy, Qdrant, one chunk per section with no merging, and **max 250 tokens per chunk** (switched from 512 on 2026-09-30: nearly equal quality at about 35% fewer tokens, see [Validation](#validation)). To recheck when other categories get their own test. Indexed: basics, bonds, stocks and etfs-and-mutual-funds, used by the chatbot's Q&A and tax agents ([§7](#7-current-index)). |
| Date | 2026-09-30 |
| Deviates from | spec §5.1 / §5.4 (FAISS, ~800-token chunks). See [Spec deviations](#spec-deviations). |

## 1. Storage hierarchy

```
Collection  finnie_kb                       one Qdrant collection for all knowledge-base articles
└── Category   basics                       payload field (a key in src/data/kb_topics.yaml, 10 total)
    └── Document   Compound interest        payload field (one article / one .md file)
        └── Section   Calculation > Periodic compounding   payload field (heading path inside the article)
            └── Chunk   the whole section (≤ 250 tokens), or one piece of a longer section
                                            one Qdrant point = one vector + payload
```

Only the **collection** is a storage container. Category, document and section are **metadata (payload) on each chunk**.

**Why not one collection per category or per section?**
- A search runs inside one collection. A question like "how often is interest compounded?" doesn't know its section in
  advance, so per-section collections (~10 per article, ~1,000 for 100 articles) would mean searching all of them and
  merging scores by hand. One collection ranks every chunk in a single query.
- Filtering by payload gives the same scoping when we want it: `category == "taxes"` for the tax agent (spec FR-K5),
  or `doc_id == "compound-interest"`.
- Separate collections are only for **different kinds of content** that shouldn't be ranked against each other, e.g. a
  future `glossary` or `news` collection.

**Chunk payload**

```python
{
    "category": "basics",
    "doc_id": "compound-interest",
    "doc_title": "Compound interest",
    "section_path": ["Calculation", "Periodic compounding"],
    "source_name": "Wikipedia",
    "source_url": "https://en.wikipedia.org/wiki/Compound_interest#Periodic_compounding",
    "chunk_index": 6,
    "text": "...",
}
```

- Point id = `uuid5(NAMESPACE_URL, "<doc_id>#<section-slug>#<n>")`, so re-running the build overwrites points
  rather than duplicating them.
- Payload indexes on `category` and `doc_id` keep filtered searches fast.

## 2. Vector database: Qdrant

| Need | Qdrant |
|---|---|
| Category filtering (FR-K5) | Native payload filters. FAISS stores vectors only and would need a side file plus our own filtering. |
| Local development | Embedded mode `QdrantClient(path=...)`, no server needed |
| Move to a managed service later | Same engine as Qdrant Cloud. Switch `qdrant_path` → `qdrant_url` + `QDRANT_API_KEY` in config and re-run the build. |
| Diverse sources in results | `query_points_groups(group_by="doc_id")` limits chunks per article |
| Exact finance terms ("401(k)", "RMD") | Optional sparse / BM25 vectors for hybrid search, added later if needed |

The index is **derived data**. The Markdown articles in git are the source of truth, so the index is rebuilt rather
than migrated, and its folder is git-ignored.

## 3. Chunking method: section-aware, measured in tokens

1. **Clean.** Wikipedia's text export spells each formula out as dozens of MathML lines. Collapse each one to inline
   LaTeX (`$A=P(1+r/n)^{tn}$`). Compound interest shrinks from 1,629 lines to 77, and its token count drops by 20%.
2. **Split by headings** into sections, keeping the full heading path (`##` down to `#####`). A heading with no text of
   its own (e.g. `## Calculation`, whose content is all in subsections) produces no chunk; it only appears in the path.
3. **One section = one chunk** when the section, with its heading prefix, is ≤ 250 tokens. Sections are **never
   merged**, however short.
4. **Split only sections over 250 tokens**, into balanced pieces of up to about 200 tokens made of whole paragraphs, with
   up to 50 tokens of overlap at each cut. A paragraph that is itself too long is cut at sentence boundaries.
5. **Prefix** each chunk with its path before embedding: `Compound interest > Calculation > Periodic compounding`.
   Without it, a chunk like "The rate is usually expressed annually…" doesn't say which rate.
6. **Count tokens with the embedding model's own tokenizer**, not with words (see §4).

**Why sections, not fixed-size windows:** a section is written as one idea, so its vector stays focused and a citation
can point to the exact `#anchor`. On the 50-page categories the median section is **208 tokens** (basics) and **148**
(bonds). About 60% of basics sections and 68% of bonds sections fit in 250 tokens, so most stay whole even at the smaller
limit (at 512 it would be about 90%).

**Why sections are not merged (decision, 2026-09-30):** each section carries its own meaning. Many short sections are
a single formula or definition (e.g. "Future value of a present sum", 36 tokens), and merging it with a neighbour
would blur that vector with an unrelated idea and make the citation point at the wrong heading. The cost is that
short sections give thinner vectors: 38 of 96 sections are under 150 tokens and 5 are under 50. The title-path prefix
offsets part of this, and the retrieval evaluation will show whether short sections are missed.

**Why not paragraphs:** the median paragraph is **63 tokens** and 88% are under 150, which is too little context for a
useful vector. Paragraphs are the units a long section is split along.

## 4. Chunk size

| Setting | Tokens | ≈ words (prose) | Reason |
|---|---|---|---|
| **max** | **250** | ~195 | A section up to this size (heading included) stays whole. Chosen over 512 for token cost (see Validation). The embedding model's own hard limit is 512: `bge-small-en-v1.5` ignores anything after 512 tokens, so no chunk may exceed that. |
| **split target** | 200 | ~155 | Piece size when a section is over 250. Balanced pieces avoid a tiny leftover tail. |
| **overlap** | 50 | ~40 | Only at cuts inside a section, so no sentence loses its setup |
| min | none | | Sections are never merged (see §3) |
| title prefix | ~10–20 | | Counted against the max |

**Tokens are not words.** Measured with the bge tokenizer:

| Text | Tokens per word |
|---|---|
| Prose | 1.23–1.28 |
| Formula-heavy sections | 1.82 (up to 2.7) |

"Compound interest › Monthly deposits" is 409 words but 772 tokens. Sized by words it looks safe, yet it would be
truncated at embedding time.

**Options compared early on** (simulated on the original six `basics` pages, 96 sections, no merging). These sizes were
later tested properly against each other; the final choice is max 250 (see Validation):

| Rule | Chunks | Median | Sections cut apart |
|---|---|---|---|
| Whole section ≤ 512, split larger into ~350 | 133 | 228 | 15 |
| Whole section ≤ 512, split larger into ~250 | 151 | 191 | 15 (into more pieces) |
| Pack paragraphs up to 250 in every section | 171 | 180 | many; sections of 250–512 are also cut, leaving tails as small as 13 tokens |
| Whole section ≤ 800 (spec size) | ~103 | ~202 | fewer, but chunks over 512 exceed bge's input and their tails aren't embedded |

**Retrieving the rest of a split section.** When a matching chunk is one piece of a split section, the retriever can
also return that section's other pieces (looked up by `doc_id` + `section_path`), so the LLM sees the full explanation.
Five results × up to 250 tokens: about 800 tokens of context per answer on average in the tests (about 1,200 at max 512).

## 5. Content choices that follow from the data

- About half of the section tokens in these pages aren't beginner material: **34%** are in sections containing
  formulas and another **18%** in history sections (e.g. "Growing annuity derivation", 1,344 tokens; "Inflation ›
  Causes › Historical approaches"). These are candidates for `drop_sections` or for rewriting as beginner summaries
  (spec FR-K7: 300–800 words "in our own words").
- Very short pages (Emergency fund: 209 tokens in two sections, so two small chunks) should be supplemented from Investor.gov or the CFPB.
- Raw Wikipedia pages average ~2,900 words. `src/kb/ingest.py` currently cuts at 800 words, which keeps the lead and
  early sections, but for long pages those are often history rather than the beginner material.

## 6. Configuration

In [config.yaml](../config.yaml):

```yaml
rag:
  qdrant_path: src/data/qdrant      # local embedded Qdrant; set qdrant_url (+ QDRANT_API_KEY in .env) for a server / Qdrant Cloud
  qdrant_url: null
  collection: finnie_kb
  categories: [basics, bonds]      # indexed categories; add one only after its token stats + retrieval test
  embedding_model: BAAI/bge-small-en-v1.5   # 384 dims, cosine; must be the same at index and query time
  max_tokens: 250                   # one chunk per section up to this; sections above it are split
  split_target_tokens: 200
  overlap_tokens: 50
  top_k: 5
  min_score: 0.68                  # provisional: below this the Q&A/tax agents fall back to live Wikipedia
```

Not built yet, still planned: dropping more low-value sections (Wikipedia's References, See also and similar are
already dropped by `src/kb/wiki.py`), returning the other pieces of a split section with a hit, and a relevance check
for off-topic questions (a plain score threshold doesn't work, see Validation).

## 7. Current index

Categories are indexed **one at a time**, each only after its own token statistics and retrieval test
(`mds/kb-token-stats-<category>.md`).

Built 2026-10-01 (etfs-and-mutual-funds added the same day) with `python -m src.rag.build_index --offline` (indexes `rag.categories` in config.yaml):

| | |
|---|---|
| Categories indexed | **basics**, **bonds**, **stocks**, **etfs-and-mutual-funds** (all tested) |
| Documents | 300 (basics 50, bonds 50, stocks 150, etfs-and-mutual-funds 50) |
| Chunks (Qdrant points) | 5,717 (basics 1,332, bonds 947, stocks 2,569, etfs-and-mutual-funds 869), median 161 tokens, max 250. These are the same chunks as the max 250 retrieval tests. |
| Source text | Full Wikipedia pages in `src/data/raw/wikipedia/<category>/` (not truncated) |
| Store | Local Qdrant at `src/data/qdrant/` (git-ignored), collection `finnie_kb` |
| Chunk list | [data/kb_index_chunks.csv](data/kb_index_chunks.csv) |

**Used by the chatbot:** the Q&A and tax agents search `finnie_kb` with the user's question (`kb_search` in
`src/workflow/tools.py`). They pass the top 5 chunks on and cite each section with a link to its `#anchor`. Below
`rag.min_score` (0.68), or if the index is missing or fails, the agent reports `not_found`. The **verifier** also
rechecks answers that pass the score: if an LLM check finds the chunks don't answer the question, they become
`not_found` too. `not_found` goes to the **research** node, which looks up LLM-chosen Wikipedia articles by exact title
(see the README's orchestrator section). The 0.68 is **provisional**. In the max 250 tests the highest out-of-scope
score is 0.667 (basics) and **0.701 (bonds)**, while the lowest answerable is 0.721 and 0.704. So for bonds no single
threshold separates them, and an off-topic question can pass 0.68. The verifier's LLM check is what catches those,
which is why it exists.

**Local Qdrant allows one process at a time.** Stop the app (`./dev.sh`) before running `build_index`, or the build
can't open `src/data/qdrant/`.

**Next categories:** full pages for every topic in `kb_topics.yaml` (50 for basics, bonds and etfs-and-mutual-funds, 150 for stocks
and goal-planning, 15 for the others) are saved in `src/data/raw/wikipedia/<category>/`.
To add a category:
1. Run `python -m scripts.kb_token_stats --category <name> --pages-dir src/data/raw/wikipedia/<name>`.
2. Write its questions (with references) and run both tests.
3. Add it to `rag.categories` and rebuild.

The articles are raw Wikipedia text, an interim source: spec FR-K7 asks for 300–800-word summaries "in our own words",
which would replace these pages and go through the same chunker. Re-running the build recreates the collection.

## Validation

These sizes come from the shape of the data, not from retrieval results. Before they're final:
1. Write 50–100 realistic beginner questions, each labelled with the section that should answer it.
2. Build the index and check whether the right section is in the top 5 (hit@5 / MRR).
3. Look specifically at questions answered by short sections (< 150 tokens) to see whether keeping them unmerged
   costs recall. Try a split target of 250 vs 350 for the long sections.

**First result (basics, 6 pages, 20 questions, 2026-09-30): max 512 adopted** (superseded by the 50-page decision below). max 512 beat max 250 on hit@5 (18 vs 17 of 18), hit@1 (13 vs 11)
and MRR (0.82 vs 0.76). Max 250 sent 40% fewer tokens to the LLM. Short unmerged sections were all found. The score
ranges of in-scope and out-of-scope questions overlap (0.555 vs 0.610), so `score_threshold` alone can't reject
off-topic questions. Details: [kb-token-stats-basics.md](kb-token-stats-basics.md#retrieval-test-max-512-vs-max-250).

**At 50 pages per category (100 pages, 63 answerable questions, 2026-09-30):** the limits are nearly level, and the
decision switched to **max 250**.

| | max 512 | max 250 |
|---|---|---|
| Correct section ranked #1 (hit@1) | **50** | 47 |
| Correct section in top 5 (hit@5) | 61 | **62** |
| Answer text in top 5 | **60** | 59 |
| MRR | **0.868** | 0.847 |
| Correctness (1–5) | **4.87** | 4.86 |
| Completeness | **0.95** | 0.94 |
| Faithfulness | 0.98 | 0.98 |
| Tokens sent to the LLM | 1,215 | **791** |

Max 512 stays slightly ahead on ranking and answer quality, but only just (correctness 4.87 vs 4.86, completeness 0.95
vs 0.94), while max 250 sends about 35% fewer tokens to the LLM on every answer. The clear max 512 lead seen at 15
pages (basics correctness 4.96 vs 4.60) narrowed as more pages were added.

**Decision (2026-09-30): switch to max 250**, because token cost matters for the product and the quality difference is
within the noise of these tests. What it costs, from the tests:
- More sections are cut into pieces (462 vs 132 across both categories), and occasionally the retrieved piece lacks
  the answer paragraph (basics q17).
- Slightly fewer questions have the right section ranked first (47 vs 50 of 63).
- Context per answer drops from about 1,215 to 791 tokens.

Watch these when the next categories are tested; if max 250 falls clearly behind there, revisit.

**Stocks (150 pages, 30 answerable questions, 2026-10-01)** supports the switch: both limits found every answer
(hit@5 30/30) and scored perfect relevance, correctness and completeness, while max 250 used about 34% fewer tokens.
**ETFs and mutual funds (50 pages, 33 answerable questions, 2026-10-01)** gives the same picture: both limits found every answer
(hit@5 33/33; MRR 0.824 at max 512, 0.813 at max 250), max 250 scored equal or better on relevance (5.00 vs 4.88) and correctness
(4.88 vs 4.82), faithfulness was lower (0.95 vs 0.99), and it sent 36% fewer tokens (748 vs 1,174). Indexed the same day.
**Goal planning (150 pages, 30 answerable questions, 2026-10-02)** agrees: both limits found every answer in the top 3, max 250
ranked slightly better (hit@1 28 vs 27, MRR 0.967 vs 0.944), answers tied on relevance, faithfulness and correctness and max 250
was a little more complete (0.91 vs 0.89), at 35% fewer tokens (778 vs 1,192). Its answers were generated and judged by `gpt-4o`
(the config's model by then), not `gpt-4o-mini`. Not indexed yet.
Totals for all tested categories: [kb-eval-summary.md](kb-eval-summary.md).

Answers were generated and judged by `gpt-4o-mini`. Faithfulness is an upper bound: one ungrounded answer (basics q16,
"bracket creep" with no supporting chunk) scored 0.80. Details: [kb-eval-summary.md](kb-eval-summary.md) and the
category docs.

## Spec deviations

| Spec | Now | Why |
|---|---|---|
| §5.1 Vector DB: FAISS | Qdrant | Native payload filtering, local → managed with no code change |
| §5.4 recursive splitter, ~800-token chunks, 100 overlap | One chunk per section (max 250); larger sections split into ~200 with up to 50 overlap | Sections keep their meaning; token cost per answer; bge-small's 512-token input limit rules out 800 (§4, Validation) |
