"""Deterministic grading. Numeric answers use the LAST number in the Answer line."""
import re
import unicodedata

_NUM = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?|-?\.\d+")
_WORDS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                       "fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}


def extract_number(s: str):
    s = unicodedata.normalize("NFKC", s or "").replace("\u2212", "-")
    nums = _NUM.findall(s)
    if nums:
        return float(nums[-1].replace(",", ""))
    words = [_WORDS[w] for w in re.findall(r"[a-z]+", s.lower()) if w in _WORDS]
    return float(words[-1]) if words else None


def norm_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower().strip().strip("*_`\"'")
    s = re.sub(r"^(the|a|an)\s+", "", s.strip())
    return re.sub(r"\s+", "", s).rstrip(".!")


def grade(q: dict, answer) -> "bool | None":
    """True/False, or None when there is no answer to grade."""
    if answer is None:
        return None
    if q["answer_type"] == "number":
        got = extract_number(str(answer))
        return None if got is None else abs(got - float(q["answer"])) <= max(float(q["tolerance"]), 1e-9)
    candidates = [q["answer"], *q.get("aliases", [])]
    if q.get("match") == "contains":
        low = unicodedata.normalize("NFKC", str(answer)).lower()
        return any(re.search(r"(?<![a-z0-9])" + re.escape(c.lower()) + r"(?![a-z0-9])", low) for c in candidates)
    return norm_text(str(answer)) in {norm_text(c) for c in candidates}


def wrong_answer(q: dict) -> str:
    """A reply that is certainly wrong for this question (used by mock models and validation)."""
    if q["answer_type"] == "number":
        v = float(q["answer"]) + max(1.0, 10 * float(q["tolerance"]))
        return str(int(v)) if v == int(v) else repr(v)
    return "zzz-unknown"


def format_number(v) -> str:
    v = float(v)
    return str(int(v)) if v == int(v) else repr(v)
