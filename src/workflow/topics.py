"""Topic memory, step 1: the turns of a conversation grouped by subject (mds/topic-memory.md).

After each reply `record_turn` gives the turn its topic (the previous turn's when the context was carried, else the next
`t<n>`), writes the turn's one-sentence `summary` into its `messages.context`, and folds the turn into the `topics` row.
`topics` is derived data: `rebuild_topic` recreates a row from the conversation's messages with the same `apply_turn`.

Summaries say what was discussed and never carry figures (prices and returns go stale; they live in `facts` with their
`as_of`), so a summary that adds a number the question doesn't have is rejected for the question itself. Every LLM step
falls back: the turn summary to the question, the topic summary to its last three turn summaries."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from src.core.llm import ask_llm

from .context import refers_back, subjectless          # rule 2 shares proofread's checks
from .jsonreply import first_json

log = logging.getLogger(__name__)

MAX_ENTITIES = 3            # companies and markets kept per topic, most recent first
MAX_SOURCES = 10            # source IDs kept per topic, the most recent
SUMMARY_SENTENCES = 3       # a topic summary's length
LABEL_CHARS = 120           # topics.label's column size

# intent → the words a label uses for it, in the order they are joined ("TSLA, SBUX performance & news")
INTENT_WORDS = {"market": "performance", "news": "news", "calc": "calculation", "tax": "tax", "goal": "savings plan",
                "portfolio": "portfolio"}
OWN_DATA_LABELS = {"portfolio": "Your portfolio", "goal": "Your savings plan"}     # topics about the user's own data

SUMMARY_SYSTEM = (
    "You keep short notes on a conversation with a personal-finance education assistant. Given the TOPIC so far (its "
    "name and summary, possibly empty) and the LATEST TURN (the user's question, what kind of question it was, the "
    "companies and markets it was about, the sources used, the start of the answer), reply with ONLY JSON:\n"
    '{"summary": "<one sentence: what the latest turn asked and covered>", '
    '"topic_summary": "<the topic so far plus the latest turn, at most 3 sentences>", '
    '"label": "<a 2 to 5 word name for the topic>"}\n'
    "Describe what was discussed, never the figures: no prices, returns, percentages, amounts or dates unless the "
    "user's question itself states them (figures go out of date). Keep the companies, markets and concepts named. "
    "Write about the user in the third person (\"The user asked…\" or \"Explained…\").")

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"“(])")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- pure helpers (tests/test_topics.py)
def next_topic_id(existing: list[str]) -> str:
    """t1, t2, …: one more than the highest number in use in the conversation."""
    nums = [int(t[1:]) for t in existing if re.fullmatch(r"t\d+", t or "")]
    return f"t{max(nums, default=0) + 1}"


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "").rstrip(".") for n in _NUMBER.findall(text or "")}


def adds_figures(text: str, *allowed: str) -> bool:
    """The text has a number none of the allowed texts (the user's questions, the summary so far) has."""
    have = set().union(*(_numbers(a) for a in allowed)) if allowed else set()
    return bool(_numbers(text) - have)


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_END.split(" ".join((text or "").split())) if s.strip()]


def clip_summary(text: str) -> str:
    return " ".join(sentences(text)[-SUMMARY_SENTENCES:])


def fallback_summary(turn_summaries: list[str]) -> str:
    """Without an LLM: the topic's last three turn summaries, each ending as a sentence."""
    parts = [s.strip() for s in turn_summaries if s and s.strip()][-SUMMARY_SENTENCES:]
    return " ".join(p if p[-1] in ".!?" else p + "." for p in parts)


def _merge_entities(old: list[dict], new: list[dict], key: str) -> list[dict]:
    """This turn's entities first, then the earlier ones it didn't name; at most MAX_ENTITIES."""
    seen, out = set(), []
    for e in [*(new or []), *(old or [])]:
        k = e.get(key) if isinstance(e, dict) else None
        if k and k not in seen:
            seen.add(k)
            out.append(e)
    return out[:MAX_ENTITIES]


def build_label(topic: dict) -> str:
    """The topic's companies or markets plus what was asked about them; "" when it has neither (the label it started
    with is kept, see apply_turn)."""
    names = [c["symbol"] for c in topic.get("companies") or [] if c.get("symbol")] or \
            [m.get("name") or m.get("key") for m in topic.get("markets") or [] if m.get("name") or m.get("key")]
    intents = topic.get("intents") or []
    if not names:
        own = next((OWN_DATA_LABELS[i] for i in intents if i in OWN_DATA_LABELS), "")
        return own
    words = [w for i, w in INTENT_WORDS.items() if i in intents and i not in OWN_DATA_LABELS]
    label = ", ".join(names[:MAX_ENTITIES]) + (" " + " & ".join(words) if words else "")
    return label[:LABEL_CHARS]


def empty_topic(topic_id: str) -> dict:
    return {"topic_id": topic_id, "label": "", "summary": "", "companies": [], "markets": [], "intents": [], "period": None,
            "facts": {}, "source_ids": [], "related": [], "message_ids": [], "turns": 0}


def apply_turn(topic: dict, ctx: dict, message_id: int | None, *, summary: str | None = None, label: str = "") -> dict:
    """The topic with one more turn folded in (a new dict). `summary` replaces the topic summary when given; `label` is
    used only while the topic has no companies, markets or own data to name it by, and only if it has no label yet."""
    out = {**empty_topic(topic.get("topic_id") or ctx.get("topic_id") or ""), **topic}
    out["companies"] = _merge_entities(out["companies"], ctx.get("companies") or [], "symbol")
    out["markets"] = _merge_entities(out["markets"], ctx.get("markets") or [], "key")
    out["intents"] = list(dict.fromkeys([*out["intents"], *(ctx.get("intents") or [])]))
    out["period"] = ctx.get("period") or out["period"]
    out["facts"] = {**(out["facts"] or {}), **(ctx.get("facts") or {})}          # latest value per symbol, whole
    out["source_ids"] = list(dict.fromkeys([*out["source_ids"], *(ctx.get("source_ids") or [])]))[-MAX_SOURCES:]
    if message_id is not None and message_id not in out["message_ids"]:
        out["message_ids"] = [*out["message_ids"], message_id]
    out["turns"] = len(out["message_ids"]) if message_id is not None else out["turns"] + 1
    if summary is not None:
        out["summary"] = clip_summary(summary)
    built = build_label(out)
    out["label"] = (built or out["label"] or label or ctx.get("question") or "")[:LABEL_CHARS]
    return out


# ---------------------------------------------------------------- entities (step 2)
CONCEPTS_PER_TURN = 2       # only a turn's top sources become concepts: broad pages would link every topic to every other
OWN_DATA_INTENTS = ("portfolio", "goal")


def slugify(text: str) -> str:
    """The knowledge base's doc_id scheme (src/kb/wiki.slugify, copied so this module stays light to import)."""
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def concept_of(source_id: str) -> str | None:
    """The concept a source is about: a KB page's doc_id, or a live Wikipedia page's title in the same slug form."""
    if source_id.startswith("kb:"):
        return source_id[3:].split("#", 1)[0] or None
    if source_id.startswith("wikipedia:"):
        title = source_id[len("wikipedia:"):].rsplit(":", 1)[0]
        return slugify(title) or None
    return None                                                     # web and news sources name no stable subject


def turn_entities(ctx: dict) -> set[tuple[str, str]]:
    """(kind, key) pairs one turn is about, from what the agents used (mds/topic-memory.md, topic_entities)."""
    keys = {("company", c["symbol"]) for c in ctx.get("companies") or [] if c.get("symbol")}
    keys |= {("market", m["key"]) for m in ctx.get("markets") or [] if m.get("key")}
    keys |= {("user_data", i) for i in ctx.get("intents") or [] if i in OWN_DATA_INTENTS}
    concepts = [c for c in (concept_of(s) for s in ctx.get("source_ids") or []) if c]
    keys |= {("concept", c) for c in list(dict.fromkeys(concepts))[:CONCEPTS_PER_TURN]}
    return keys


def topic_entities(topic: dict, earlier: set[tuple[str, str]] = frozenset(), ctx: dict | None = None) -> set[tuple[str, str]]:
    """A topic's entity set after a turn: its current companies, markets and own-data intents, plus every concept its
    turns have had (`earlier` holds the stored rows, `ctx` the turn just added)."""
    keys = {("company", c["symbol"]) for c in topic.get("companies") or [] if c.get("symbol")}
    keys |= {("market", m["key"]) for m in topic.get("markets") or [] if m.get("key")}
    keys |= {("user_data", i) for i in topic.get("intents") or [] if i in OWN_DATA_INTENTS}
    keys |= {k for k in earlier if k[0] == "concept"}
    if ctx:
        keys |= {k for k in turn_entities(ctx) if k[0] == "concept"}
    return keys


def message_entities(state: dict) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """What a message names, from the router's resolved entities: (hard, soft). Hard keys are companies, markets and the
    user's own data; rule 5: when it names a company, only its companies count. Soft keys are concepts guessed from the
    wording ("swing trading" → swing-trading); a miss on them never rules a topic out."""
    e = state.get("entities") or {}
    intents = state.get("intent") or []
    companies = {("company", c["symbol"]) for c in e.get("companies") or [] if isinstance(c, dict) and c.get("symbol")}
    companies |= {("company", t) for t in e.get("tickers") or [] if t and not t.startswith("^")}
    if companies:
        hard = companies
    else:
        hard = {("market", m["key"]) for m in e.get("markets") or [] if isinstance(m, dict) and m.get("key")}
        hard |= {("user_data", i) for i in intents if i in OWN_DATA_INTENTS}
    soft = set()
    if {"qa", "tax"} & set(intents) and e.get("wiki_query"):
        soft = {("concept", slugify(e["wiki_query"]))}
    return hard, soft


# ---------------------------------------------------------------- topic assignment (steps 2-3)
SINCE_LAST_TIME = re.compile(r"\bsince (?:we |i )?(?:last|the last time|we talked|we spoke|then|before)\b|\bcompared (?:to|with) (?:last time|before)\b", re.I)


def _cosine(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = sum(x * x for x in a) ** 0.5, sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def _keys(cand: dict) -> set[tuple[str, str]]:
    return {tuple(k) for k in cand.get("entities") or []}


def _overlap(hard: set, cand: dict) -> int:
    kinds = {k for k, _ in hard}
    return len(hard & {k for k in _keys(cand) if k[0] in kinds})


def as_context(cand: dict) -> dict:
    """A topic from this chat as the turn's `context_in`: its subject, period and figures fill in what the message leaves
    out, as the previous answer's context does for a follow-up."""
    return {"question": cand.get("last_question") or cand.get("label") or "", "intents": cand.get("intents") or [],
            "companies": cand.get("companies") or [], "markets": cand.get("markets") or [], "levels": [],
            "tab": None, "symbol": None, "period": cand.get("period"), "facts": cand.get("facts") or {},
            "topic_id": cand.get("topic_id"), "source_ids": cand.get("source_ids") or []}


def background(linked: list[dict], *, since_last_time: bool = False) -> str:
    """Earlier chats' topics as a dated note for the reply: what was discussed, never figures, unless the user asks how
    something changed since then, when the dated figures come in for comparison."""
    if not linked:
        return ""
    lines = ["EARLIER CONVERSATIONS (background only; fetch every figure live, never present these as current):"]
    for c in linked:
        lines.append(f"- {(c.get('updated_at') or '')[:10]}: {c.get('summary') or c.get('label') or ''}".rstrip())
        if since_last_time:
            for sym, f in (c.get("facts") or {}).items():
                bits = [f"price {f['price']:,.2f}" if isinstance(f.get("price"), (int, float)) else "",
                        f"{f.get('period', 'period')} return {f['return'] * 100:+.1f}%" if isinstance(f.get("return"), (int, float)) else ""]
                bits = [b for b in bits if b]
                if bits:
                    lines.append(f"  {sym} then (as of {f.get('as_of') or 'that day'}, for comparison only): " + "; ".join(bits))
    return "\n".join(lines)


def choose(state: dict, pool: dict, *, embed=None, same_chat: float = 0.8, earlier_chat: float = 0.86, max_linked: int = 3) -> dict:
    """Which topic a message belongs to (mds/topic-memory.md, "Topic assignment"). `pool` is {"current": [...], "earlier":
    [...]}: this chat's topics and the session's other chats' topics, as `candidates()` loads them. Returns
    {action, topic_id, related, linked, note} plus `context` for a reopened topic; action is one of continue (the
    previous turn's topic), reopen (an older topic of this chat), link (a new topic linked to earlier chats) or new.
    `embed(texts) -> vectors | None` is only called for a message with no entities (rule 4)."""
    ctx = state.get("context_in") or {}
    current_id = ctx.get("topic_id")
    current = [c for c in pool.get("current") or []]
    earlier = [c for c in pool.get("earlier") or []]
    question = state.get("question") or ""

    def decided(action, topic_id=None, note="", related=(), linked=(), cand=None):
        out = {"action": action, "topic_id": topic_id, "related": [c["uid"] for c in related if c.get("uid")],
               "linked": [{"uid": c.get("uid"), "date": (c.get("updated_at") or "")[:10], "label": c.get("label") or ""}
                          for c in linked], "note": f"topic: {note}"}
        if cand is not None:
            out["context"] = as_context(cand)
        if linked:
            out["background"] = background(list(linked), since_last_time=bool(SINCE_LAST_TIME.search(question)))
        return out

    def recent(cands):
        return sorted(cands, key=lambda c: c.get("updated_at") or "", reverse=True)

    def in_chat(cand, why, others=()):
        if cand.get("topic_id") == current_id:
            return decided("continue", current_id, f"{why} → stays in {current_id}", related=others)
        return decided("reopen", cand["topic_id"], f"{why} → back to {cand['topic_id']} ({cand.get('label')})", related=others, cand=cand)

    if state.get("follow_up"):
        return decided("continue", current_id, f"follow-up → stays in {current_id}" if current_id else "follow-up of an untracked turn → new topic")
    if current_id and not state.get("screen") and subjectless(state.get("original_question") or question):
        return decided("continue", current_id, f"no subject of its own → stays in {current_id}")             # rule 2
    if current_id and not state.get("screen") and refers_back(state.get("original_question") or question):
        return decided("continue", current_id, f"points back at the previous answer → stays in {current_id}")  # rule 2
    hard, soft = message_entities(state)
    keys = hard or soft
    if keys:
        named = ", ".join(k for _, k in sorted(keys))
        here = recent([c for c in current if (_overlap(hard, c) if hard else soft & _keys(c))])
        if here:                                                                                  # rules 3 and 5
            return in_chat(here[0], f"{named} matches", others=here[1:])
        there = sorted([c for c in earlier if (_overlap(hard, c) if hard else soft & _keys(c))],
                       key=lambda c: (_overlap(hard, c) / max(1, len(_keys(c))) if hard else 1, c.get("updated_at") or ""), reverse=True)
        if there:
            linked = there[:max_linked]
            return decided("link", None, f"{named} discussed in {len(linked)} earlier chat(s) → new topic, linked", related=linked, linked=linked)
        if hard:                                                                                  # rule 1
            return decided("new", None, f"{named} matches no topic → new topic")
    vec = None                                                                                    # rule 4
    if embed is not None and (current or earlier):
        got = embed([question])
        vec = got[0] if got else None
    if vec is not None:
        scored = [(_cosine(vec, c.get("summary_vec")), c) for c in current]
        best = max(scored, key=lambda s: s[0], default=(0.0, None))
        if best[1] is not None and best[0] >= same_chat:
            return in_chat(best[1], f"close to “{best[1].get('label')}” ({best[0]:.2f})")
        far = sorted(((_cosine(vec, c.get("summary_vec")), c) for c in earlier), key=lambda s: s[0], reverse=True)
        linked = [c for s, c in far if s >= earlier_chat][:max_linked]
        if linked:
            return decided("link", None, f"close to {len(linked)} earlier chat topic(s) → new topic, linked", related=linked, linked=linked)
    return decided("new", None, "no matching topic → new topic")


# ---------------------------------------------------------------- embeddings (step 3; tests switch them off)
_embedder: object = "default"


def set_topic_embedder(fn) -> None:
    """Tests inject `fn(texts) -> list[vector]`, or None to turn topic embeddings off; "default" is the KB's bge-small."""
    global _embedder
    _embedder = fn


def embed(texts: list[str]) -> list[list[float]] | None:
    """Vectors for the texts, or None when embeddings are off or fail (rule 4 is then skipped)."""
    fn = _embedder
    if fn is None or not texts:
        return None
    try:
        if fn == "default":
            from src.core.config import get_config
            if not (get_config().get("topics") or {}).get("embeddings", True):
                return None
            from src.rag.store import get_embedder
            return [v.tolist() for v in get_embedder().embed(list(texts))]
        return [list(v) for v in fn(list(texts))]
    except Exception as e:  # noqa: BLE001 — topic memory must never break a turn
        log.warning("topic embeddings unavailable: %s", e)
        return None


# ---------------------------------------------------------------- summaries (one LLM call per turn)
ANSWER_CHARS = 700          # how much of the reply the summary sees: enough to say what it covered


def _turn_prompt(topic: dict, ctx: dict, source_titles: list[str], answer: str = "") -> str:
    def names(items, key):
        return ", ".join(i.get("name") or i.get(key) for i in items or [] if i.get("name") or i.get(key)) or "none"
    return (f"TOPIC: {topic.get('label') or '(new)'}\nSUMMARY SO FAR: {topic.get('summary') or '(none)'}\n\n"
            f"LATEST TURN\nQuestion: {ctx.get('question') or ''}\nKind: {', '.join(ctx.get('intents') or []) or 'qa'}\n"
            f"Companies: {names(ctx.get('companies'), 'symbol')}\nMarkets: {names(ctx.get('markets'), 'key')}\n"
            f"Sources: {'; '.join(source_titles[:5]) or 'none'}"
            + (f"\nAnswer (start; say what it covered, not its figures): {' '.join(answer.split())[:ANSWER_CHARS]}" if answer else ""))


def summarize_turn(topic: dict, ctx: dict, *, earlier_turns: list[str], earlier_questions: list[str],
                   source_titles: list[str] | None = None, answer: str = "") -> tuple[str, str, str]:
    """(turn summary, topic summary, label) for a turn about to join `topic`. One LLM call; any part the model leaves
    out, or that adds a figure the user's questions don't have, falls back (the question; the last three turn summaries;
    "" so the label is built from the topic)."""
    question = ctx.get("question") or ""
    allowed = [question, *earlier_questions]
    data = first_json(ask_llm(SUMMARY_SYSTEM, _turn_prompt(topic, ctx, source_titles or [], answer))) or {}
    turn = str(data.get("summary") or "").strip()
    if not turn or adds_figures(turn, *allowed):
        turn = question
    merged = str(data.get("topic_summary") or "").strip()
    if not merged or adds_figures(merged, *allowed):
        merged = fallback_summary([*earlier_turns, turn])
    label = str(data.get("label") or "").strip().strip("\"'.")
    if adds_figures(label, *allowed):
        label = ""
    return turn, merged, label[:LABEL_CHARS]


def summarize_topic(turn_summaries: list[str], questions: list[str]) -> str:
    """A rebuilt topic's summary: one call over all its turn summaries (instead of merging them one at a time)."""
    if not turn_summaries:
        return ""
    notes = "\n".join(f"- {s}" for s in turn_summaries)
    reply = first_json(ask_llm(SUMMARY_SYSTEM, f"TOPIC: (rebuilding)\nTURN NOTES, oldest first:\n{notes}\n\n"
                                               "Reply with the JSON; put the whole topic in topic_summary.")) or {}
    merged = str(reply.get("topic_summary") or "").strip()
    return merged if merged and not adds_figures(merged, *questions, *turn_summaries) else fallback_summary(turn_summaries)


# ---------------------------------------------------------------- database
def _as_dict(row) -> dict:
    keys = ("topic_id", "label", "summary", "companies", "markets", "intents", "period", "facts", "source_ids", "related",
            "message_ids", "turns")
    return {k: getattr(row, k) for k in keys}


def _store(row, topic: dict) -> None:
    for k in ("label", "summary", "companies", "markets", "intents", "period", "facts", "source_ids", "related", "message_ids", "turns"):
        setattr(row, k, topic[k])
    row.updated_at = _now()


def _store_entities(row, session_id: str, keys: set[tuple[str, str]]) -> None:
    """Rewrite the topic's topic_entities rows to `keys` (kept rows stay, so no delete-and-insert of the same key)."""
    from src.db.models import TopicEntity
    keys = {(k, v[:80]) for k, v in keys}
    row.entities[:] = [e for e in row.entities if (e.kind, e.key) in keys]
    have = {(e.kind, e.key) for e in row.entities}
    row.entities.extend(TopicEntity(kind=k, key=v, session_id=session_id) for k, v in sorted(keys - have))


def _refresh_vector(row) -> None:
    got = embed([row.summary]) if row.summary else None
    row.summary_vec = got[0] if got else row.summary_vec


def _assistant_turns(conv, topic_id: str | None = None) -> list:
    rows = [m for m in conv.messages if m.role == "assistant" and isinstance(m.context, dict) and m.context.get("topic_id")]
    return [m for m in rows if topic_id is None or m.context["topic_id"] == topic_id]


def _source_titles(message) -> list[str]:
    return [s.get("title", "") for s in message.sources or [] if isinstance(s, dict) and s.get("title")]


def _candidate(row, last_question: str = "") -> dict:
    """A topics row as the topic node sees it (plain JSON, so it can sit in the graph state)."""
    return {**_as_dict(row), "uid": row.uid, "conversation_id": row.conversation_id,
            "updated_at": row.updated_at.isoformat() if row.updated_at else "", "summary_vec": row.summary_vec,
            "entities": sorted([e.kind, e.key] for e in row.entities), "last_question": last_question}


def candidates(db, conv, *, earlier: bool = True, limit: int | None = None) -> dict:
    """The topics a new message may belong to: this chat's, and (unless `earlier` is False) the session's other chats'
    most recently updated ones. Never raises: without them the turn simply starts or continues a topic as in step 1."""
    from src.core.config import get_config
    from src.db.models import Topic
    limit = limit or int((get_config().get("topics") or {}).get("earlier_candidates", 50))
    try:
        last_q = {m.context["topic_id"]: m.context.get("question") or "" for m in _assistant_turns(conv)}
        current = [_candidate(t, last_q.get(t.topic_id, "")) for t in conv.topics]
        others = []
        if earlier:
            rows = (db.query(Topic).filter(Topic.session_id == conv.session_id, Topic.conversation_id != conv.id)
                    .order_by(Topic.updated_at.desc()).limit(limit).all())
            others = [{**_candidate(t), "facts": t.facts or {}} for t in rows]
        return {"current": current, "earlier": others}
    except Exception:  # noqa: BLE001
        log.exception("topic memory: loading topics failed")
        return {"current": [], "earlier": []}


def record_turn(db, conv, message) -> dict | None:
    """Give a just-saved assistant `message` its topic and fold it into the `topics` row (created when new): the summary,
    the entities, the links to earlier chats and the summary's embedding. Returns the topic as a dict, or None for a
    reply without a context (empty or failed turns). Never raises: topic memory must not break a chat, so a failure is
    logged and the reply stands."""
    from src.db.models import Topic
    ctx = dict(message.context or {})
    if not ctx:
        return None
    try:
        topic_id = ctx.get("topic_id") or next_topic_id([t.topic_id for t in conv.topics])
        row = next((t for t in conv.topics if t.topic_id == topic_id), None)
        if row is None:
            row = Topic(session_id=conv.session_id, conversation_id=conv.id, topic_id=topic_id)
            conv.topics.append(row)
        topic = _as_dict(row) if row.turns else empty_topic(topic_id)
        topic["related"] = list(dict.fromkeys([*(topic.get("related") or []), *(ctx.get("related") or [])]))
        earlier = [m for m in _assistant_turns(conv, topic_id) if m.id != message.id]
        turn_summary, merged, label = summarize_turn(
            topic, ctx, earlier_turns=[m.context.get("summary") or m.context.get("question") or "" for m in earlier],
            earlier_questions=[m.context.get("question") or "" for m in earlier], source_titles=_source_titles(message),
            answer=message.content or "")
        message.context = {**ctx, "topic_id": topic_id, "summary": turn_summary}     # a new dict, so the JSON column is saved
        before = {(e.kind, e.key) for e in row.entities}
        topic = apply_turn(topic, message.context, message.id, summary=merged, label=label)
        _store(row, topic)
        _store_entities(row, conv.session_id, topic_entities(topic, before, message.context))
        _refresh_vector(row)
        db.commit()
        return topic
    except Exception:  # noqa: BLE001
        log.exception("topic memory: recording the turn failed")
        db.rollback()
        return None


def drop_links(db, conv, topic_id: str | None) -> None:
    """"Answer without them": forget the earlier chats a topic was linked to."""
    row = next((t for t in conv.topics if t.topic_id == topic_id), None)
    if row is not None and row.related:
        row.related = []
        db.commit()


def rebuild_topic(db, conv, topic_id: str) -> dict | None:
    """Recreate a topic from the conversation's messages: replay its turns in order with apply_turn, then write the
    summary with one call over all the turn summaries. Deletes the row and returns None when no turn is left in it."""
    from src.db.models import Topic
    turns = sorted(_assistant_turns(conv, topic_id), key=lambda m: m.id)
    row = next((t for t in conv.topics if t.topic_id == topic_id), None)
    if not turns:
        if row is not None:
            conv.topics.remove(row)
            db.commit()
        return None
    topic = empty_topic(topic_id)
    start_label = (row.label if row is not None else "") or turns[0].context.get("question") or ""   # kept for a topic with no entities
    concepts: set[tuple[str, str]] = set()
    for m in turns:
        topic = apply_turn(topic, m.context, m.id, label=start_label)
        topic["related"] = list(dict.fromkeys([*topic["related"], *(m.context.get("related") or [])]))
        concepts |= {k for k in turn_entities(m.context) if k[0] == "concept"}
    topic["summary"] = clip_summary(summarize_topic([m.context.get("summary") or m.context.get("question") or "" for m in turns],
                                                    [m.context.get("question") or "" for m in turns]))
    if row is None:
        row = Topic(session_id=conv.session_id, conversation_id=conv.id, topic_id=topic_id)
        conv.topics.append(row)
    _store(row, topic)
    _store_entities(row, conv.session_id, topic_entities(topic, concepts))
    _refresh_vector(row)
    db.commit()
    return topic
