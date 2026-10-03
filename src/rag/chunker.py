"""Section-aware chunking (mds/rag-data-design.md §3-4).

One section = one chunk when it fits in `max_tokens` (heading prefix included). Sections are never merged. A longer
section is split into balanced pieces of about `split_target` tokens, built from whole paragraphs (sentences only when
a paragraph is itself too long), and each piece after the first repeats up to `overlap` tokens from the end of the one
before it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .text import clean, count_tokens, get_tokenizer, paragraphs, sections, sentences


@dataclass
class Chunk:
    doc_id: str
    doc_title: str
    category: str
    section: str               # "(lead)" or "Parent > Child"
    section_tokens: int
    piece: int                 # 0-based position within the section
    pieces: int
    text: str
    source_url: str

    @property
    def heading(self) -> str:
        return self.doc_title if self.section == "(lead)" else f"{self.doc_title} > {self.section}"

    @property
    def embed_text(self) -> str:
        return f"{self.heading}\n\n{self.text}"

    @property
    def tokens(self) -> int:
        return count_tokens(self.embed_text)

    @property
    def id(self) -> str:
        return f"{self.doc_id}#{self.section}#{self.piece}"


def _hard_split(text: str, limit: int) -> list[str]:
    """Cut text into windows of at most `limit` tokens, for a sentence that is longer than a chunk (long formulas)."""
    enc = get_tokenizer().encode(text, add_special_tokens=False)
    out = []
    for start in range(0, len(enc.ids), limit):
        window = enc.offsets[start:start + limit]
        out.append(text[window[0][0]:window[-1][1]])
    return out


def _units(body: str, limit: int) -> list[tuple[str, int]]:
    """Paragraphs, or the sentences of any paragraph over `limit`, each with its token count."""
    units = []
    for para in paragraphs(body):
        t = count_tokens(para)
        if t <= limit:
            units.append((para, t))
            continue
        for sent in sentences(para):
            for piece in ([sent] if count_tokens(sent) <= limit else _hard_split(sent, limit)):
                units.append((piece, count_tokens(piece)))
    return units


def _tail(units: list[tuple[str, int]], overlap: int) -> list[tuple[str, int]]:
    """Whole trailing sentences of a piece, up to `overlap` tokens."""
    sents = [(s, count_tokens(s)) for s in sentences(" ".join(u for u, _ in units))]
    tail, total = [], 0
    for s, t in reversed(sents):
        if total + t > overlap:
            break
        tail.insert(0, (s, t))
        total += t
    return tail


def split_section(body: str, budget: int, split_target: int, overlap: int) -> list[str]:
    """Split a section body into balanced pieces, each at most `budget` tokens including the overlap."""
    cap = max(budget - overlap, 1)
    target = min(split_target, cap)
    units = _units(body, cap)
    total = sum(t for _, t in units)
    goal = total / max(math.ceil(total / target), 1)
    groups, cur, cur_t = [], [], 0
    for u, t in units:
        if cur and (cur_t + t > cap or cur_t >= goal):
            groups.append(cur)
            cur, cur_t = [], 0
        cur.append((u, t))
        cur_t += t
    if cur:
        groups.append(cur)
    pieces = []
    for i, g in enumerate(groups):
        head = _tail(groups[i - 1], overlap) if i and overlap else []
        pieces.append("\n\n".join([" ".join(s for s, _ in head)] * bool(head) + [u for u, _ in g]))
    return pieces


def chunk_document(doc_id: str, title: str, category: str, source_url: str, raw_text: str, *,
                   max_tokens: int = 512, split_target: int = 350, overlap: int = 50) -> list[Chunk]:
    chunks = []
    for section, _, body in sections(clean(raw_text)):
        body = body.strip()
        if not body:
            continue                                   # heading with only subsections: appears in their paths
        probe = Chunk(doc_id, title, category, section, 0, 0, 1, "", source_url)
        budget = max_tokens - count_tokens(probe.heading + "\n\n")
        section_tokens = count_tokens(body)
        pieces = [body] if section_tokens <= budget else split_section(body, budget, split_target, overlap)
        chunks += [Chunk(doc_id, title, category, section, section_tokens, i, len(pieces), text, source_url)
                   for i, text in enumerate(pieces)]
    return chunks
