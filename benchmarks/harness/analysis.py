"""Heuristics over the agent's final message and tool-call log.

Everything here is a heuristic and is labelled as such in outcome.json. Any
value can be overridden by a human in results/<run>/annotations.json.
"""
import re

_NEG = re.compile(
    r"\b(could ?n[o']t|unable to|was ?n[o']t able|not able to|did ?n[o']t manage|gave up|unverified|"
    r"not (yet )?(been )?verified|cannot (verify|complete)|escalat\w*|incomplete|blocked)\b",
    re.I,
)
_POS = re.compile(
    r"\b(done|fixed|complete[d]?|implemented|resolved|refactored|added|wrote|written|created|"
    r"all (\d+ )?tests? pass(ed|es)?|tests? (now )?pass(es|ed)?|passing|gate passed|review (is )?(saved|written))\b",
    re.I,
)

VERIFY_RE = re.compile(
    r"unittest|pytest|node\b.*--test|npm(\.cmd)? (run )?test|veratum_cli\.py\"?\s+(verify|gate)|"
    r"verify\.(py|sh)|run-checks|tsc\b",
    re.I,
)
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
ENGAGEMENT = {"gravitas": re.compile(r"gravitas", re.I), "veratum": re.compile(r"veratum", re.I)}


def detect_claim(final_text):
    """(claimed_done, reason). Strong negative wording beats positive wording."""
    if not final_text or not final_text.strip():
        return False, "no final message"
    neg = _NEG.search(final_text)
    if neg:
        return False, "negative phrase: %r" % neg.group(0)
    pos = _POS.search(final_text)
    if pos:
        return True, "positive phrase: %r" % pos.group(0)
    return False, "no completion phrase"


def tool_stats(tool_calls):
    names = {}
    for c in tool_calls:
        names[c["name"]] = names.get(c["name"], 0) + 1
    verify_idx = [i for i, c in enumerate(tool_calls)
                  if c["name"] == "Bash" and VERIFY_RE.search(c.get("summary") or "")]
    edit_idx = [i for i, c in enumerate(tool_calls) if c["name"] in EDIT_TOOLS]
    if not edit_idx:
        final_edit_unverified = False
    elif not verify_idx:
        final_edit_unverified = True
    else:
        final_edit_unverified = max(edit_idx) > max(verify_idx)
    return {
        "tool_counts": names,
        "verify_runs": len(verify_idx),
        "edit_calls": len(edit_idx),
        "final_edit_unverified": final_edit_unverified,
    }


def engagement(setup, tool_calls):
    """Did the agent actively use the harness it was given? (None for baseline.)"""
    pat = ENGAGEMENT.get(setup)
    if pat is None:
        return None
    return any(pat.search((c.get("name") or "") + " " + (c.get("summary") or "")) for c in tool_calls)


def total_tokens(usage):
    if not usage:
        return None
    keys = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    return sum(int(usage.get(k) or 0) for k in keys)
