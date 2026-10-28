"""Question schema and validation."""
import re

from .common import QUESTIONS_PATH, HASH_PATH, load_json, recorded_hash, sha256_file

CATEGORIES = ("arithmetic", "number_theory", "units", "calendar", "strings", "logic_traps", "facts", "code")
DIFFICULTIES = ("easy", "medium", "hard")
ANSWER_TYPES = ("number", "text")
MATCHES = ("exact", "contains")


def load_questions(path=QUESTIONS_PATH):
    return load_json(path)


def validate(rows) -> list:
    from .grading import grade, wrong_answer  # local import avoids a cycle
    errs = []
    if not isinstance(rows, list) or not rows:
        return ["top level must be a non-empty array"]
    ids, texts = set(), set()
    for i, q in enumerate(rows):
        if not isinstance(q, dict):
            errs.append(f"row {i}: not an object"); continue
        qid = q.get("id"); tag = qid if isinstance(qid, str) else f"row {i}"
        if not isinstance(qid, str) or not re.fullmatch(r"CQ\d{3}", qid): errs.append(f"{tag}: id must look like CQ001")
        if qid in ids: errs.append(f"{tag}: duplicate id")
        ids.add(qid)
        if not isinstance(q.get("question"), str) or not q["question"].strip(): errs.append(f"{tag}: empty question")
        elif q["question"] in texts: errs.append(f"{tag}: duplicate question text")
        else: texts.add(q["question"])
        if q.get("category") not in CATEGORIES: errs.append(f"{tag}: category must be one of {list(CATEGORIES)}")
        if q.get("difficulty") not in DIFFICULTIES: errs.append(f"{tag}: difficulty must be one of {list(DIFFICULTIES)}")
        t = q.get("answer_type")
        if t not in ANSWER_TYPES: errs.append(f"{tag}: answer_type must be one of {list(ANSWER_TYPES)}"); continue
        if q.get("match") not in MATCHES: errs.append(f"{tag}: match must be one of {list(MATCHES)}")
        tol = q.get("tolerance")
        if isinstance(tol, bool) or not isinstance(tol, (int, float)) or tol < 0: errs.append(f"{tag}: tolerance must be a number >= 0")
        if not isinstance(q.get("aliases"), list) or any(not isinstance(a, str) for a in q["aliases"]): errs.append(f"{tag}: aliases must be an array of strings")
        a = q.get("answer")
        if t == "number" and (isinstance(a, bool) or not isinstance(a, (int, float))): errs.append(f"{tag}: numeric answer must be a number"); continue
        if t == "text" and (not isinstance(a, str) or not a.strip()): errs.append(f"{tag}: text answer must be a non-empty string"); continue
        if errs and tag in " ".join(errs): continue
        try:  # every question must grade its own answer as right and a deliberately wrong answer as wrong
            if grade(q, str(a)) is not True: errs.append(f"{tag}: its own answer is not graded correct")
            for al in q["aliases"]:
                if grade(q, al) is not True: errs.append(f"{tag}: alias {al!r} is not graded correct")
            if grade(q, wrong_answer(q)) is True: errs.append(f"{tag}: the built-in wrong answer is graded correct")
        except Exception as e:  # pragma: no cover
            errs.append(f"{tag}: grading failed: {e}")
    return errs


def check_hash(path=QUESTIONS_PATH):
    rec, act = recorded_hash(HASH_PATH), sha256_file(path)
    if rec is None: return [f"no SHA-256 found in {HASH_PATH}"]
    if rec != act:
        return [f"question-set SHA-256 changed: recorded {rec[:12]}..., actual {act[:12]}... "
                "(run `python -m calibrate validate --write-hash` if the edit was intentional)"]
    return []
