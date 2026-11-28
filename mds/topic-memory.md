# Topic memory

**Status: built (steps 1-3), not yet tuned.** The similarity thresholds are provisional (`topics:` in `config.yaml`).
Before this, each turn started
only from the previous answer's `context` (`src/workflow/context.py`). Topic memory groups turns about the same subject,
so a message can pick a subject up from further back ("back to Tesla", three turns after TSLA was discussed) or from an
earlier chat.

## Data

`messages` keeps one row per message and is never changed after it is written, except that the assistant row's
`context` gets its `summary` right after the reply. `topics` is one row per topic, built from those messages and
updated after every turn. `topic_entities` indexes topics by what they are about.

```
sessions
  └── conversations
        ├── messages      context.topic_id points to a topic
        └── topics        message_ids points back
              └── topic_entities   one row per entity
```

### `messages.context` (existing column, new fields)

Assistant rows only. The existing fields stay as `build()` wrote them before; the shape is `TurnContext` in
`src/workflow/state.py`.

```json
{
  "question": "How have TSLA and SBUX performed over the last month?",
  "intents": ["market"],
  "companies": [{"symbol": "TSLA", "name": "Tesla"}, {"symbol": "SBUX", "name": "Starbucks"}],
  "markets": [], "levels": ["company"], "tab": "Chat", "symbol": null,
  "period": {"label": "1 month", "start": "2026-09-30"},
  "facts": {"TSLA": {"return": 0.072, "as_of": "2026-10-30"}, "SBUX": {"return": -0.031, "as_of": "2026-10-30"}},

  "topic_id": "t1",
  "summary": "Compared TSLA and SBUX performance over the last month.",
  "source_ids": []
}
```

| New field | Meaning |
|---|---|
| `topic_id` | The topic this turn belongs to: a counter per conversation, `t1`, `t2`, … |
| `summary` | One sentence on what was discussed, written after the reply. **No figures** (see Staleness). Without an LLM, or when the model's sentence has a number the question doesn't, it is the question. |
| `source_ids` | Every source ID the turn cited, from the reply's sources. |
| `related` | `topics.uid` of the earlier chats' topics this turn was linked to (topic node). |
| `linked` | The same for the UI, `[{uid, date, label}]`; `MessageOut.linked` serves it. |

Rows written before this change lack these fields; readers use `.get()` with defaults, so nothing is migrated.

### Source IDs

| Origin | Format | Fetched again by |
|---|---|---|
| Knowledge base | `kb:<doc_id>#<section>` | Qdrant filter on `doc_id` + `section` (all pieces of the section) |
| Live Wikipedia | `wikipedia:<title>:<revision_id>` | that exact revision |
| Web search | `web:<url>` | a fresh search (the page may have changed) |
| News | `news:<story_id>` | the news collection |

`doc_id` is `slugify(page title)` (`build_index.py`), so "Expense ratio" is `expense-ratio`. `section` is the heading
path (`chunker.py`): `(lead)` before the first heading, `Parent > Child` below it. Market turns have no source IDs;
their evidence is `facts`, and a follow-up fetches live data again anyway.

### `topics` (table, `src/db/models.py`)

| Column | Type | Holds | Updated |
|---|---|---|---|
| `uid` | VARCHAR(32) PK | unique across conversations | set once |
| `session_id` | FK → sessions | the user's session | set once |
| `conversation_id` | FK → conversations, cascade | the chat the topic lives in | set once |
| `topic_id` | VARCHAR(8) | `t1`; unique with `conversation_id` | set once |
| `label` | VARCHAR(120) | "TSLA, SBUX performance", for display and logs | rebuilt every turn |
| `summary` | TEXT | the whole topic in at most 3 sentences, **no figures** | merged every turn |
| `companies`, `markets` | JSON | most recent first, at most 3 each | every turn |
| `intents` | JSON | union across turns | every turn |
| `period` | JSON | the latest period used | every turn |
| `facts` | JSON | the latest value per symbol, each with `as_of` | every turn |
| `source_ids` | JSON | union, the 10 most recent | every turn |
| `related` | JSON | `uid`s of linked topics: earlier chats, and other topics of this chat a turn also matched (rule 3) | topic assignment |
| `message_ids` | JSON | the assistant rows in this topic | every turn |
| `turns` | INTEGER | count | every turn |
| `summary_vec` | JSON | embedding of `summary` (bge-small) | when `summary` changes |
| `created_at`, `updated_at` | DATETIME | `updated_at` ranks by recency | |

Example after "what is the stock TSLA performance?" then "hows' TSLA vs SBUX performance?":

```json
{
  "topic_id": "t1",
  "label": "TSLA, SBUX performance",
  "summary": "Looked at how TSLA stock has performed. Compared TSLA and SBUX performance over the last month.",
  "companies": [{"symbol": "TSLA", "name": "Tesla"}, {"symbol": "SBUX", "name": "Starbucks"}],
  "markets": [], "intents": ["market"],
  "period": {"label": "1 month", "start": "2026-09-30"},
  "facts": {"TSLA": {"return": 0.072, "as_of": "2026-10-30"}, "SBUX": {"return": -0.031, "as_of": "2026-10-30"}},
  "source_ids": [], "related": [],
  "message_ids": [602, 604], "turns": 2
}
```

### `topic_entities`

| Column | Type | Holds |
|---|---|---|
| `topic_uid` | FK → topics.uid, cascade | |
| `session_id` | VARCHAR, indexed with `key` | cross-chat lookup without a join |
| `kind` | VARCHAR(16) | company, market, concept, user_data |
| `key` | VARCHAR(80), indexed | `TSLA`, `sector:technology`, `swing-trading` |

Primary key (`topic_uid`, `kind`, `key`). Filled in code after each turn from what the agents actually used, not from
the raw message:

| kind | Example key | From |
|---|---|---|
| `company` | `TSLA` | `context.companies` |
| `market` | `group:us_indices`, `sector:technology` | `context.markets` (their `key`) |
| `concept` | `expense-ratio` | the turn's top 1-2 KB or Wikipedia sources (`doc_id` / `slugify(title)`) |
| `user_data` | `portfolio`, `goal` | intent `portfolio` / `goal` |

Only the top 1-2 sources become concepts: broad pages ("Stock", "Risk") would otherwise link every topic to every
other. Web sources give no entity; a URL is not a stable subject. The planned `calc` kind (the calculator function that
ran) is left out: the turn's context doesn't record which function ran.

For the message itself (before any agent runs) the topic node uses the router's resolved entities: companies and
tickers, else markets and the user's own data (rule 5). A concept is guessed from the wording (`slugify` of the
router's `wiki_query` for a Q&A or tax question: "what is swing trading?" → `swing-trading`); a guess that matches no
topic never rules one out, so the message goes on to the embedding check.

## Staleness

| Part of a topic | Goes stale? |
|---|---|
| Entities, what was asked, the period chosen | No |
| Concept explanations | Barely (only when the KB is rebuilt) |
| Prices, returns | Yes, within minutes |
| News | Yes, within hours |
| The user's portfolio or plan | Yes: the user can edit it |

Every stale part is a value, so values never go in a summary: `summary` says what was discussed and `facts` holds the
numbers with their `as_of`. How a topic is used:

| Where | Carried | Values |
|---|---|---|
| The same chat | everything | `facts` fill in what a follow-up leaves out; agents fetch fresh data anyway |
| An earlier chat | the dated `summary` only, as background | never; always fetched live |
| Portfolio, goal | that the user asked about it | read from the database, never from a topic |
| News | that the user followed it | searched again |

One exception: "how has TSLA changed since we last talked?" asks for an old value. Only then do the old `facts` come in,
labelled with their date, next to today's live figure.

## Labels

Built in code from the topic's fields: `<companies or markets, most recent 3> + <intent words>`, with `market` →
"performance", `news` → "news", `calc` → "calculation", `tax` → "tax", `goal` → "savings plan", `portfolio` →
"portfolio". "TSLA performance" becomes "TSLA, SBUX performance" when SBUX joins, and "TSLA, SBUX performance & news"
when news is asked. A topic with no companies or markets keeps the label it started with: the LLM's short name for it
(from the same call that writes the summary), else the question.

## Topic assignment

Without topics (`run_chat` called without `topics`, as most workflow tests do) a turn continues the previous turn's
topic only when proofread marks it a follow-up; otherwise it starts a new topic. A calculation is no exception: "How much will $10,000 grow at 7%?" after "What is an ETF?" is a new
topic, while "How much will $10,000 grow at 7% on this ETF?" points back ("this") and stays in the ETF topic.
(`build()` still lets a calculation keep the earlier companies, `context.KEEPS_SUBJECT`; that decides what the turn
is about, not which topic it joins.)

One edge: "this ETF" also matches the on-screen check (`context.screen`). If the user has switched to another tab or
symbol since the last answer, the message is read as about the screen, is not a follow-up, and starts a new topic.

The chat API loads the candidates (`topics.candidates`: this chat's topics and the session's 50 most recently
updated topics from other chats) and the `topic` node (`nodes.topic_node`, logic in `topics.choose`) runs after the
router (proofread → router → topic → agents), so it uses the router's resolved entities (`_routed` →
`symbols.subjects`) rather than extracting its own. Reopening an older topic of this chat makes its subject, period
and figures the turn's `context_in` and sets `follow_up`, as for a follow-up. Continuing the previous turn's topic on
entities alone changes nothing else (`follow_up` is set only for rule 2). Guard replies (read-only, off-topic,
clarify) get no topic decision.

```
proofread → rewritten question + follow_up
   ▼
router → intents + resolved entities
   ▼
topic
   ├─ follow_up = true ─────────────────────────────────────► current topic
   └─ follow_up = false
        ├─ no entities, no subject of its own ("show example") ► current topic            (rule 2)
        ├─ entities (companies first: rule 5)
        │     1. this chat's topics   ─ match ──► continue it; several ► most recent       (rule 3)
        │     2. earlier chats' topics ─ match ──► new topic, linked (related)
        │     3. none ────────────────────────► new topic, no embedding check             (rule 1)
        └─ no entities but a subject ("how should I think about risk at 30?")
              ► cosine(question, summary_vec): this chat, then earlier chats (stricter threshold)   (rule 4)
```

1. **Entities present, none overlap → new topic, skip embeddings.** "How is the market doing today?" after an SPY vs
   NVDA question scores close on wording but is a different subject.
2. **No entities and no subject of its own → continue the current topic**, whatever `follow_up` says. The follow-up
   regex also gains "show", "example", "explain more", "more detail".
   A message that points back at the previous answer's case ("how would the tax change in this case?", "what about
   that scenario?", `context.refers_back`) also continues it, and proofread completes it with that answer's worked
   example (`context.with_scenario`), even when the proofread model calls it a new question.
3. **Several topics match → continue the most recent and link the rest.** "Can we do swing trading on NVIDIA?" after an
   NVDA topic and a swing-trading topic continues swing trading and links the NVDA topic.
4. **Embeddings are the last resort**: only for messages with no entities that do have a subject.
5. **A named company decides.** If the message names a company, match on companies only; markets count only when no
   company is named. "Is the market favorable to NVDA?" must not join the US-market topic.

`follow_up` stays: it is the only check that reads the conversation, and short messages ("which did better?", "compare
to starbucks") are where embeddings are worst. Proofread also reads the current topic's summary ("Topic so far: …"
under CONTEXT), so a follow-up two turns from the subject still resolves. It looks back one turn only; the topic search
covers everything further back. Without an LLM, `context.looks_like_follow_up` also accepts a message with no subject
of its own (`context.subjectless`: "show example", "tell me more", "why?"), narrower on purpose than a list of words:
"can you give an example of compound interest?" names its subject.

On a follow-up, the Q&A and tax agents also fetch the topic's knowledge-base sections again (`tools.kb_fetch` →
`store.search_sections`, scored against the new question) and rank them with the fresh search's hits, each chunk once.

### Earlier chats

1. A new chat always gets a new topic; a topic from an earlier chat is never continued, only linked.
2. A link is background only: the old topic's companies, intents and period are not added to the turn. Only its dated
   summary goes in, at most 3, newest first.
3. The router's intents come from the new message alone; router rule 10 (inherit intents) is for follow-ups in the same
   chat.

| Entity kind | Link when |
|---|---|
| company / market | at least one shared company or market (companies first) |
| concept | the same `doc_id` |
| calc | the same calculator function |
| user_data | always (it is read live anyway) |
| none | embedding ≥ the cross-chat threshold, set above the same-chat one: a wrong link is worse than none |

```
EARLIER CONVERSATIONS (for context only; fetch all figures live):
- 2026-10-03: Compared TSLA and SBUX performance over one month.
```

Linked chats are used automatically and shown under the reply: "Using 1 earlier chat (TSLA, SBUX performance) ·
Answer without them". The button sends the same question again with `no_memory: true`: the previous reply's topic
drops its links (`topics.drop_links`) and earlier chats are not searched for that turn. The notes reach the reply only
through the LLM synthesizer, so in basic mode topics are still linked but no line is shown.

## After each turn

```
reply ready
   ▼
compliance → context.build()    existing fields + topic_id (when carried) + source_ids
   ▼
save the messages row
   ▼
topics.record_turn()
     topic_id: carried, else the next t<n>
     one LLM call → turn summary + topic summary (+ a label for a topic with no entities)
       fallback: summary = question; topic summary = last 3 turn summaries
     apply_turn(): companies/markets/intents/source_ids merged, period/facts = latest,
                   message_ids += id, turns += 1, label rebuilt
   ▼
upsert the topics row, rewrite its topic_entities rows, embed its summary
```

`record_turn` never raises: a failure is logged and the reply stands. The streaming endpoint sends the reply before
recording the topic, so the summary call doesn't delay the answer; the plain `/chat` endpoint records it inline.

## Rebuilding a topic (`topics.rebuild_topic`)

`topics` is derived data; the `messages` rows are the source of truth.

```
assistant rows WHERE conversation_id = ? AND context.topic_id = ? ORDER BY id
   ├─ none ──► delete the topics row
   ▼
start empty → apply_turn() for each row in order (the same function as the live path)
   ▼
summary = one LLM call over all the turn summaries (fallback: the last 3)
   ▼
upsert
```

For a summary merge gone wrong, an update-code bug, a rule change (label format, a new field), a turn put in the wrong
topic (change its `topic_id`, rebuild both), and to backfill old conversations.

## Walkthroughs

**1. SPY, market, swing trading**

| # | Message | follow_up | Entities | Topic |
|---|---|---|---|---|
| 1 | how's the spy performs against nvidia | false | SPY, NVDA | new t1 "SPY, NVDA performance" |
| 2 | hows' market going on today? | false | us_indices | no overlap → new t2 (rule 1) |
| 3 | what is swing trading? | false | concept swing-trading | new t3 "Swing trading" |
| 4 | show example | true (LLM) / false (no LLM) | none | t3 either way (rule 2) |
| 5 | can we do swing trading on nvidia? | either | NVDA, swing-trading | t1 and t3 match → continue t3, link t1 (rule 3) → "NVDA swing trading" |

**2. Tax, market, Tesla, NVDA**

| # | Message | follow_up | Entities | Topic |
|---|---|---|---|---|
| 1 | what is tax return? | false | concept from Wikipedia (not an indexed category) | new t1 "Tax return" |
| 2 | hows' today market trend? | false | us_indices | new t2 "US market performance & news" |
| 3 | what stocks. earn the most | true (no subject or period of its own) | — | t2; period `today` carried. Ambiguous wording: say which reading was taken |
| 4 | ho'ws tesla stock doing? | false | TSLA | new t3 "TSLA performance"; default period, not `today` |
| 5 | is it up or down? | true | — | t3 ("it" is the last turn's TSLA) |
| 6 | is the market favorite to nvda? | false | NVDA (+ "the market") | rule 5: companies only → new t4 |

**3. A second chat after "TSLA, SBUX performance" in the first**, as consecutive messages:

| # | Message | Topic |
|---|---|---|
| 1 | any news on Tesla? | new t1, linked to the first chat's topic |
| 2 | TSLA vs NVDA this year? | continue t1 (this chat first); SBUX is not added |
| 3 | does Tesla pay a dividend? | continue t1 |
| 4 | how's AMD doing? | new t2, no link |
| 5 | how should I compare two stocks? | rule 4, likely new t3, no link |

## Without an LLM

Every LLM step keeps a non-LLM path (`CLAUDE.md`). The summary falls back to the question, the topic summary to the
last 3 turn summaries, labels are built in code, and assignment uses the regex follow-up check. One gap: the keyword
router used to miss lowercase company names ("ho'ws tesla stock doing?" went to Q&A). `symbols.lowercase_mentions` now
finds them next to a cue ("tesla stock", "how's tesla doing"), for the 500 best-ranked companies only and never for
funds or kinds of stock ("growth stock", "first stock"), as many names are everyday words ("save for a visa"); such a
message then goes to the market agent (`_with_listed_tickers`). Rule 4 is off without embeddings, and earlier chats'
notes are only read by the LLM synthesizer.

## Code

| Piece | Where |
|---|---|
| Tables | `Topic`, `TopicEntity` in `src/db/models.py`; `Message.linked` for the API |
| Turn context fields | `context.build()`; shape `TurnContext` in `src/workflow/state.py` |
| Assignment, entities, labels, summaries, rebuild | `src/workflow/topics.py` (`choose`, `record_turn`, `rebuild_topic`, `candidates`) |
| Topic node, proofread topic summary, source re-fetch, background for the synthesizer | `src/workflow/nodes.py` |
| Graph edge router → topic, flow panel entry | `src/workflow/graph.py` |
| Loading topics, "Answer without them" | `src/api/routers/chat.py` (`ChatIn.no_memory`) |
| UI line | `frontend/src/components/ChatTab.tsx` |
| Settings | `topics:` in `config.yaml` |
| Tests | `tests/test_topics.py`; conftest turns topic embeddings off (`set_topic_embedder`) |
