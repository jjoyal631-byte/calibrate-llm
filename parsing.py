"""Extract the answer and stated confidence from a model reply. Uses the LAST occurrence of each line."""
import json
import re

_ANS = re.compile(r"(?im)^[ \t>#*_`-]*answer[ \t*_`]*[:\-][ \t*_`]*(.+?)[ \t*_`]*$")
_CONF = re.compile(r"(?im)^[ \t>#*_`-]*confidence(?: level)?[ \t*_`]*[:\-][ \t*_`~]*(-?\d+(?:\.\d+)?)[ \t]*(%?)")


def parse_response(text: str) -> dict:
    """Return {answer, confidence (percent 0-100 or None), flags, error}. Never raises."""
    out = {"answer": None, "confidence": None, "flags": [], "error": None}
    text = text or ""
    a, c = _ANS.findall(text), _CONF.findall(text)
    if a:
        out["answer"] = a[-1].strip()
    if c:
        raw, pct = c[-1]
        v = float(raw)
        if pct == "%" or v > 1 or v == 0:
            conf = v
        elif 0 < v < 1:
            conf, out["flags"] = v * 100, ["fraction_converted"]
        else:  # exactly 1 without a percent sign: 1% or probability 1.0?
            conf, out["error"] = None, "ambiguous confidence '1' (percent or probability?)"
        if conf is not None and not 0 <= conf <= 100:
            conf, out["error"] = None, f"confidence {raw} outside 0-100"
        out["confidence"] = conf
    if out["answer"] is None or out["confidence"] is None:  # JSON fallback: {"answer": ..., "confidence": ...}
        for m in re.finditer(r"\{[^{}]*\}", text):
            try:
                d = json.loads(m.group(0))
            except json.JSONDecodeError:
                continue
            if isinstance(d, dict) and "answer" in d and out["answer"] is None:
                out["answer"] = str(d["answer"]).strip()
            if isinstance(d, dict) and isinstance(d.get("confidence"), (int, float)) and not isinstance(d["confidence"], bool) and out["confidence"] is None:
                v = float(d["confidence"])
                if 0 <= v <= 100 and v != 1:
                    out["confidence"], out["error"] = (v * 100 if 0 < v < 1 else v), None
    if out["answer"] is None:
        out["error"] = out["error"] or "no 'Answer:' line"
    elif out["confidence"] is None and not out["error"]:
        out["error"] = "no 'Confidence:' line"
    return out
