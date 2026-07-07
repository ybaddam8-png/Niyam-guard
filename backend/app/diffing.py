"""
Doc feature: 'Redline diff view — every detected change is shown as an actual
old-text/new-text redline (struck-through vs. highlighted)'.
Pure stdlib (difflib), no LLM involved — deterministic and fully testable offline.
"""
import difflib
import html


def make_redline_html(old_text: str, new_text: str) -> str:
    """Word-level redline: <del> for removed words, <ins> for added words.

    Uses SequenceMatcher on whitespace-split tokens so partial-word changes
    inside a longer clause render as a real redline, not a full-line replace.
    """
    old_tokens = old_text.split()
    new_tokens = new_text.split()
    matcher = difflib.SequenceMatcher(a=old_tokens, b=new_tokens)
    out = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        old_chunk = html.escape(" ".join(old_tokens[i1:i2]))
        new_chunk = html.escape(" ".join(new_tokens[j1:j2]))
        if tag == "equal":
            out.append(old_chunk)
        elif tag == "replace":
            out.append(f'<del class="redline-del">{old_chunk}</del> <ins class="redline-ins">{new_chunk}</ins>')
        elif tag == "delete":
            out.append(f'<del class="redline-del">{old_chunk}</del>')
        elif tag == "insert":
            out.append(f'<ins class="redline-ins">{new_chunk}</ins>')
    return " ".join(p for p in out if p)


def similarity_ratio(old_text: str, new_text: str) -> float:
    """0.0 (completely different) to 1.0 (identical). Used to decide in_sync vs out_of_sync
    when the system text isn't an exact string match but might still be semantically current."""
    return difflib.SequenceMatcher(a=old_text, b=new_text).ratio()
