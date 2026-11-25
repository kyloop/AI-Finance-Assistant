"""Section-aware chunking (mds/rag-data-design.md §3-4).

One section = one chunk when it fits in `max_tokens` (heading prefix included). Sections are never merged. A longer
section is split into balanced pieces of about `split_target` tokens, built from whole paragraphs (sentences only when
a paragraph is itself too long), and each piece after the first repeats up to `overlap` tokens from the end of the one
before it.
"""
from __future__ import annotations

import re

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


# US-only categories (rag.us_only): a section about another country is left out. Its path names the country or region
# ("By country > Portugal", "Around the world > Romania", "Canada > Land transfer tax"), or sits under a world-tour heading
# that isn't about the US. The lead and US sections are kept, so "Capital gains tax" keeps its US part.
FOREIGN = re.compile(
    r"\b(Afghanistan|Albania|Algeria|Argentina|Armenia|Australia|Austria|Azerbaijan|Bangladesh|Barbados|Belarus|Belgium|"
    r"Bolivia|Bosnia|Botswana|Brazil|Bulgaria|Cambodia|Cameroon|Canada|Canadian|Chile|China|Chinese|Colombia|Costa Rica|"
    r"Croatia|Cyprus|Czech|Denmark|Dominican|Ecuador|Egypt|Estonia|Ethiopia|Fiji|Finland|France|French|Georgia \(country\)|"
    r"Germany|German|Ghana|Greece|Guatemala|Hong Kong|Hungary|Iceland|India|Indian|Indonesia|Iran|Iraq|Ireland|Irish|Israel|"
    r"Italy|Italian|Jamaica|Japan|Japanese|Jordan|Kazakhstan|Kenya|Korea|Kosovo|Kuwait|Latvia|Lebanon|Liechtenstein|"
    r"Lithuania|Luxembourg|Macau|Malaysia|Malta|Mauritius|Mexico|Moldova|Monaco|Mongolia|Montenegro|Morocco|Nepal|"
    r"Netherlands|Dutch|New Zealand|Nigeria|Norway|Pakistan|Panama|Paraguay|Peru|Philippines|Poland|Portugal|Puerto Rico|"
    r"Qatar|Romania|Russia|Rwanda|Saudi|Serbia|Singapore|Slovakia|Slovenia|South Africa|Spain|Sri Lanka|Sweden|Swiss|"
    r"Switzerland|Taiwan|Tanzania|Thailand|Tunisia|Turkey|Uganda|Ukraine|United Arab Emirates|UAE|United Kingdom|UK|"
    r"Britain|British|Uruguay|Venezuela|Vietnam|Zambia|Zimbabwe|European|Europe|EU|Scotland|Wales|England|Ontario|Quebec|"
    r"Alberta|Asia|Asian|Africa|African|Latin America|Caribbean|Nordic|Scandinavia|OECD)\b")
WORLD_TOUR = re.compile(r"^(by country|by jurisdiction|by nation|by region|around the world|worldwide|international|"
                        r"other countries|in other countries|outside the united states|other jurisdictions|"
                        r"countries|global|comparison by country|national (systems|implementations))\b", re.I)
US = re.compile(r"\b(United States|U\.S\.|US|USA|American|federal)\b")


def foreign_section(path: str, title: str = "") -> bool:
    """Whether a section (its heading path, "A > B > C") is about somewhere other than the US. On a page about the US
    ("Sales taxes in the United States"), "By jurisdiction > Utah" is a state, so only a named country counts."""
    if path == "(lead)" or US.search(path):
        return False
    if FOREIGN.search(path):
        return True
    return not US.search(title) and any(WORLD_TOUR.match(part.strip()) for part in path.split(" > "))


def chunk_document(doc_id: str, title: str, category: str, source_url: str, raw_text: str, *,
                   max_tokens: int = 512, split_target: int = 350, overlap: int = 50, us_only: bool = False) -> list[Chunk]:
    chunks, seen = [], {}
    for section, _, body in sections(clean(raw_text)):
        body = body.strip()
        if not body:
            continue                                   # heading with only subsections: appears in their paths
        if us_only and foreign_section(section, title):
            continue
        seen[section] = seen.get(section, 0) + 1
        if seen[section] > 1:                          # a page with two "History" sections: keep both (same id otherwise)
            section = f"{section} ({seen[section]})"
        probe = Chunk(doc_id, title, category, section, 0, 0, 1, "", source_url)
        budget = max_tokens - count_tokens(probe.heading + "\n\n")
        section_tokens = count_tokens(body)
        pieces = [body] if section_tokens <= budget else split_section(body, budget, split_target, overlap)
        chunks += [Chunk(doc_id, title, category, section, section_tokens, i, len(pieces), text, source_url)
                   for i, text in enumerate(pieces)]
    return chunks
