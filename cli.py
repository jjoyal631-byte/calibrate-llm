"""Command line interface: python -m calibrate <command>."""
import argparse
import os
import sys
from collections import Counter

from . import __version__
from .common import QUESTIONS_PATH, HASH_PATH, sha256_file
from .prompts import STYLES, build_messages
from .providers import MOCK_POLICIES, MockProvider, OpenAICompatible
from .questions import check_hash, load_questions, validate
from .report import write_report
from .runner import run_experiment


def _select(qs, ids, limit):
    if ids:
        want = [i.strip() for i in ids.split(",") if i.strip()]
        unknown = set(want) - {q["id"] for q in qs}
        if unknown:
            raise SystemExit(f"Unknown question IDs: {sorted(unknown)}")
        qs = [q for q in qs if q["id"] in want]
    return qs[:limit] if limit else qs


def cmd_list(a):
    qs = load_questions(a.questions)
    for q in qs:
        print(f"{q['id']}  {q['category']:<14} {q['difficulty']:<7} {q['question'][:70]}")
    c = Counter(q["category"] for q in qs)
    print(f"\n{len(qs)} questions: " + ", ".join(f"{k} {v}" for k, v in sorted(c.items())))


def cmd_validate(a):
    errs = validate(load_questions(a.questions))
    if errs:
        print("\n".join("ERROR " + e for e in errs)); return 1
    if a.write_hash:
        HASH_PATH.write_text(f"SHA-256 data/questions.json: {sha256_file(a.questions)}\nRecompute after intentional question edits "
                             "(python -m calibrate validate --write-hash); never compare runs across different hashes without noting the change.\n", encoding="utf-8")
        print("Recorded hash", sha256_file(a.questions)); return 0
    if a.check_hash:
        errs = check_hash(a.questions)
        if errs:
            print("\n".join("ERROR " + e for e in errs)); return 1
    print(f"Valid question set: {len(load_questions(a.questions))} questions"); return 0


def cmd_prompt(a):
    q = next((q for q in load_questions(a.questions) if q["id"] == a.question_id), None)
    if not q:
        raise SystemExit(f"Unknown question {a.question_id}")
    for m in build_messages(q, a.style):
        print(f"--- {m['role']} ---\n{m['content']}\n")


def cmd_run(a):
    qs, styles = _select(load_questions(a.questions), a.question_ids, a.limit), [s.strip() for s in a.styles.split(",")]
    if set(styles) - set(STYLES):
        raise SystemExit(f"Unknown prompt styles {sorted(set(styles) - set(STYLES))}; choose from {list(STYLES)}")
    if a.repeats < 1:
        raise SystemExit("--repeats must be >= 1")
    if a.dry_run:
        for q in qs[:3]:
            for st in styles:
                print(f"=== {q['id']} [{st}] ===")
                for m in build_messages(q, st):
                    print(f"--- {m['role']} ---\n{m['content']}\n")
        print(f"Dry run: {len(qs)} questions x {len(styles)} styles x {a.repeats} repeats = {len(qs) * len(styles) * a.repeats} requests "
              "(first 3 questions shown). No network used."); return 0
    if a.provider.startswith("mock:"):
        provider = MockProvider(a.provider.split(":", 1)[1])
    elif a.provider == "openai":
        base, key, model = (os.environ.get(k, "") for k in ("OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL"))
        if not (base and key and model):
            raise SystemExit("Set OPENAI_BASE_URL, OPENAI_API_KEY and OPENAI_MODEL (check provider pricing first), "
                             "or use --provider mock:calibrated for a free simulated run, or --dry-run.")
        provider = OpenAICompatible(base, key, model, a.temperature, a.max_tokens, a.timeout, a.retries, a.backoff)
    else:
        raise SystemExit(f"--provider must be 'openai' or 'mock:<{'|'.join(MOCK_POLICIES)}>'")
    n = run_experiment(provider, qs, styles, a.repeats, a.out, a.questions, resume=not a.no_resume)
    print(f"Finished: {n['collected']} collected, {n['skipped']} skipped, {n['failed']} failed. Raw output in {a.out}.")
    if provider.synthetic:
        print("These are SIMULATED results; the report excludes them unless you pass --include-synthetic.")
    return 1 if n["failed"] else 0


def cmd_report(a):
    rep = write_report(a.runs, a.questions, load_questions(a.questions), a.out, a.include_synthetic, a.bins, a.boot)
    ex = rep["excluded"]
    print(f"Wrote {a.out}/report.md, report.html, summary.json, results.csv ({len(rep['groups'])} model/prompt groups; "
          f"excluded {ex['synthetic']} simulated, {ex['errors']} errored)")
    if not rep["groups"] and ex["synthetic"]:
        print("All runs were simulated. Add --include-synthetic to demonstrate the report (never publish those numbers).")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="calibrate", description="Measure whether an AI's confidence matches its accuracy.")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--questions", default=str(QUESTIONS_PATH))
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    v = sub.add_parser("validate"); v.add_argument("--check-hash", action="store_true"); v.add_argument("--write-hash", action="store_true"); v.set_defaults(fn=cmd_validate)
    pr = sub.add_parser("prompt"); pr.add_argument("question_id"); pr.add_argument("--style", default="direct", choices=STYLES); pr.set_defaults(fn=cmd_prompt)
    r = sub.add_parser("run", help="collect raw replies from a model")
    r.add_argument("--provider", default="openai", help="'openai' (env-configured) or mock:<policy>")
    r.add_argument("--styles", default="direct", help="comma list from: " + ",".join(STYLES))
    r.add_argument("--repeats", type=int, default=1); r.add_argument("--limit", type=int, default=0, help="max questions (0 = all)")
    r.add_argument("--question-ids"); r.add_argument("--out", default="results/runs.jsonl")
    r.add_argument("--temperature", type=float, default=0.0); r.add_argument("--max-tokens", type=int)
    r.add_argument("--timeout", type=float, default=90); r.add_argument("--retries", type=int, default=3); r.add_argument("--backoff", type=float, default=2.0)
    r.add_argument("--no-resume", action="store_true"); r.add_argument("--dry-run", action="store_true"); r.set_defaults(fn=cmd_run)
    rp = sub.add_parser("report", help="grade stored replies and write a report")
    rp.add_argument("--runs", default="results/runs.jsonl"); rp.add_argument("--out", default="results/report")
    rp.add_argument("--bins", type=int, default=5, help="confidence bins (default 5; few questions => few bins)")
    rp.add_argument("--boot", type=int, default=1000, help="bootstrap resamples for intervals (0 disables)")
    rp.add_argument("--include-synthetic", action="store_true"); rp.set_defaults(fn=cmd_report)
    a = p.parse_args(argv)
    return a.fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
