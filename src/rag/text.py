"""Text preparation shared by the chunker and the token statistics (mds/rag-data-design.md §3)."""
from __future__ import annotations

import re
from functools import lru_cache

TOKENIZER = "BAAI/bge-small-en-v1.5"


@lru_cache
def get_tokenizer():
    from tokenizers import Tokenizer
    tok = Tokenizer.from_pretrained(TOKENIZER)
    tok.no_truncation()
    return tok


def count_tokens(text: str) -> int:
    """Tokens as the embedding model sees them, without [CLS]/[SEP]."""
    return len(get_tokenizer().encode(text, add_special_tokens=False).ids) if text.strip() else 0


def count_words(text: str) -> int:
    return sum(1 for w in text.split() if w.strip("#"))


def clean(text: str) -> str:
    """Collapse MathML dumps (indented token lines ending in {\\displaystyle ...}) into inline $latex$; one paragraph per line."""
    lines, out, after_math, i = text.split("\n"), [], False, 0
    while i < len(lines):
        s = " ".join(lines[i].split())
        if s.startswith("{\\displaystyle"):
            latex, depth = s, s.count("{") - s.count("}")
            while depth > 0 and i + 1 < len(lines):          # a formula can wrap over several lines
                i += 1
                latex += " " + lines[i].strip()
                depth += lines[i].count("{") - lines[i].count("}")
            latex = " ".join(latex[len("{\\displaystyle"):].rsplit("}", 1)[0].split())
            if not out or out[-1] == "":
                out.append(f"${latex}$")
            else:
                out[-1] += f" ${latex}$"
            after_math = True
        elif s == "" or lines[i].startswith("  "):
            pass                                              # MathML token lines and blank padding
        else:
            continues = after_math and out and not (s.startswith("#") or (s[:1].isupper() and out[-1].rstrip().endswith((".", ":"))))
            if continues:
                out[-1] += ("" if s[:1] in ",.;:)" else " ") + s
            else:
                if out and out[-1] != "":
                    out.append("")
                out.append(s)
                if s.startswith("#"):
                    out.append("")
            after_math = False
        i += 1
    return "\n".join(out).strip() + "\n"


def sections(text: str):
    """Yield (path, depth, body) per heading; path is "(lead)" or "Parent > Child"; the lead is depth 0, "##" depth 1."""
    stack, depth, body = [], 0, []
    for line in text.split("\n"):
        m = re.match(r"(#{2,6}) (.*)", line)
        if m:
            yield (" > ".join(h for _, h in stack) or "(lead)"), depth, "\n".join(body)
            level = len(m.group(1))
            stack = [(lv, h) for lv, h in stack if lv < level] + [(level, m.group(2))]
            depth, body = level - 1, []
        else:
            body.append(line)
    yield (" > ".join(h for _, h in stack) or "(lead)"), depth, "\n".join(body)


def paragraphs(text: str) -> list[str]:
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z$(\"'])", text) if s.strip()]
