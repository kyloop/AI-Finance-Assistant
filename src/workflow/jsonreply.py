"""The first JSON object in an LLM reply, shared by the workflow nodes and the calculator pipeline."""
from __future__ import annotations

import json
import re

# A backslash JSON can't read as written: LaTeX copied from a source (\mu, \cdot, \left), or a LaTeX command that
# starts like an escape and would silently become a control character (\beta -> backspace + "eta", \frac, \times,
# \nu, \rho). Doubled, it reads as the backslash the source has. "\\" pairs are matched first and kept.
_LATEX = (r"\\\\|\\(?:(?=[bf][A-Za-z])|(?=(?:nu|neq|nabla|not|right|rho|rangle|text[a-z]*|times|theta|tau|tfrac|top)"
          r"(?![a-z]))|(?=u(?![0-9a-fA-F]{4}))|(?![\"\\/bfnrtu]))")


def _escaped(text: str) -> str:
    return re.sub(_LATEX, lambda m: m[0] if m[0] == "\\\\" else "\\\\", text)


def _starts(text: str) -> list[int]:
    """Where an outermost object can start: each "{" outside strings at the reply's top level. A stray "{" that never
    closes lowers the level (the object after it counts as top level); a stray "}" is ignored."""
    depth, starts, in_str, esc = 0, [], False, False
    for i, ch in enumerate(text):
        if in_str:
            in_str, esc = (ch != '"' or esc), (ch == "\\" and not esc)
        elif ch == '"':
            in_str = True
        elif ch == "{":
            starts.append((i, depth))
            depth += 1
        elif ch == "}":
            depth = max(depth - 1, 0)
    excess = depth                                      # braces still open at the end: stray leading ones
    return [i for i, d in starts if d <= excess]


def _rejoined(text: str) -> str:
    """An object closed early and a new one opened ({"inputs": {...}},{"derived": ...}, seen in gpt-4o-mini replies)
    read as one: inside an object a "{" can't follow a comma, so that "{" is dropped (the "}" left over at the end is
    ignored). Arrays of objects are untouched."""
    out, stack, in_str, esc, prev = [], [], False, False, ""
    for ch in text:
        if in_str:
            in_str, esc = (ch != '"' or esc), (ch == "\\" and not esc)
        elif ch == '"':
            in_str = True
        elif ch == "{" and prev == "," and stack[-1:] == ["{"]:
            continue
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]" and stack:
            stack.pop()
        out.append(ch)
        if not ch.isspace():
            prev = ch
    return "".join(out)


def first_json(reply: str | None) -> dict | None:
    """The first complete JSON object in an LLM reply, or None. Text around it, including stray extra braces (seen in
    gpt-4o-mini replies), is ignored; LaTeX backslashes in its strings are read as written; an object closed early is
    rejoined. An object nested in a reply that still isn't valid JSON is not returned: it would be read as the whole
    reply."""
    escaped = _escaped(reply or "")
    for text in dict.fromkeys((escaped, _rejoined(escaped))):
        for start in _starts(text):
            try:
                obj, _ = json.JSONDecoder().raw_decode(text, start)
            except ValueError:
                continue
            return obj if isinstance(obj, dict) else None
    return None
