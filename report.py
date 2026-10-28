"""Grade stored replies and compute calibration metrics per (model, prompt style)."""
import datetime
import html
import json
from collections import defaultdict
from pathlib import Path

from . import __version__
from .common import sha256_file, wilson, write_csv
from .grading import grade
from .metrics import mean, summarize
from .parsing import parse_response

WARNING = ("Calibration is measured on a small, fixed question set of mostly easy-to-verify questions. With a few dozen questions "
           "the intervals are wide, and good calibration here does not imply good calibration on other tasks. "
           "Do not rank models whose intervals overlap.")
SIM_BANNER = "SIMULATED RESULTS: produced by built-in mock models to demonstrate the pipeline. Never report these as real."
HIGH_CONF = 90


def load_runs(path):
    rows, bad = [], 0
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                bad += 1
    return rows, bad


def _split(items, key):
    d = defaultdict(list)
    for i in items:
        d[i[key]].append(i)
    return {k: {"n": len(v), "accuracy": round(mean([x["correct"] for x in v]), 4),
                "mean_confidence": round(mean([x["conf"] for x in v]), 4)} for k, v in sorted(d.items())}


def build_report(runs, questions, include_synthetic=False, n_bins=5, boot_reps=1000, questions_sha=None):
    by_id = {q["id"]: q for q in questions}
    ex = {"synthetic": 0, "errors": 0, "unknown_question": 0}
    other_sha, groups, per_run = 0, defaultdict(lambda: {"items": [], "fail": [], "errors": 0}), []
    for r in runs:
        g = (r.get("model_requested", "?"), r.get("style", "?"))
        if r.get("synthetic") and not include_synthetic:
            ex["synthetic"] += 1; continue
        if "error" in r:
            ex["errors"] += 1; groups[g]["errors"] += 1; continue
        q = by_id.get(r.get("question_id"))
        if q is None:
            ex["unknown_question"] += 1; continue
        if questions_sha and r.get("question_set_sha256") != questions_sha:
            other_sha += 1
        p = parse_response(r.get("text", ""))
        correct = grade(q, p["answer"]) if p["answer"] is not None else None
        row = {"question_id": q["id"], "category": q["category"], "difficulty": q["difficulty"], "model": g[0], "style": g[1],
               "repeat": r.get("repeat"), "answer": p["answer"], "confidence": p["confidence"],
               "correct": correct, "parse_error": p["error"] or "", "expected": q["answer"]}
        per_run.append(row)
        if p["answer"] is None or p["confidence"] is None or correct is None:
            groups[g]["fail"].append(row)
        else:
            groups[g]["items"].append({"qid": q["id"], "conf": p["confidence"] / 100, "correct": int(correct),
                                       "category": q["category"], "difficulty": q["difficulty"], "rowref": row})
    out = []
    for (model, style), d in sorted(groups.items()):
        items = d["items"]
        s = summarize(items, n_bins, boot_reps)
        total = len(items) + len(d["fail"])
        out.append({"model": model, "style": style, "runs": total, "scored": len(items), "format_failures": len(d["fail"]),
                    "format_failure_rate": round(len(d["fail"]) / total, 4) if total else None,
                    "errors": d["errors"], "metrics": s,
                    "by_category": _split(items, "category"), "by_difficulty": _split(items, "difficulty"),
                    "high_confidence_errors": sorted({i["qid"] for i in items if i["conf"] * 100 >= HIGH_CONF and not i["correct"]})})
    rep = {"tool": "CALIBRATE", "version": __version__, "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
           "question_set_sha256": questions_sha, "runs_from_other_question_hash": other_sha, "bins": n_bins,
           "includes_synthetic": include_synthetic and any(r.get("synthetic") for r in runs), "excluded": ex,
           "groups": out, "warning": WARNING}
    return rep, per_run


def _f(x, d=3):
    return "n/a" if x is None else f"{x:.{d}f}"


def _ci(m, k):
    c = m.get(k + "_ci95_bootstrap")
    return "" if not c else f" [{c[0]:.3f}, {c[1]:.3f}]"


def render_markdown(rep) -> str:
    L = ["# CALIBRATE report", ""]
    if rep["includes_synthetic"]:
        L += [f"> **{SIM_BANNER}**", ""]
    ex = rep["excluded"]
    L += [f"Question set `{(rep['question_set_sha256'] or '?')[:12]}...` | {rep['bins']} confidence bins | excluded: {ex['synthetic']} simulated, "
          f"{ex['errors']} errored, {ex['unknown_question']} unknown-question runs.", ""]
    if rep["runs_from_other_question_hash"]:
        L += [f"> Warning: {rep['runs_from_other_question_hash']} run(s) used a different question-set hash.", ""]
    if not rep["groups"]:
        return "\n".join(L + ["No scored runs. (Simulated runs need `--include-synthetic`.)", ""])
    L += ["## Summary", "", "Brier and ECE: lower is better. Skill > 0 beats always saying your average accuracy. AUROC 0.5 means confidence "
          "says nothing about correctness. Gap = mean confidence minus accuracy (positive = overconfident).", "",
          "| Model | Prompt | Scored | Accuracy | Mean conf. | Gap | Brier | Skill | ECE | AUROC | Format fails |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for g in rep["groups"]:
        m = g["metrics"]
        if not m["n"]:
            L.append(f"| {g['model']} | {g['style']} | 0 | | | | | | | | {g['format_failures']}/{g['runs']} |"); continue
        L.append(f"| {g['model']} | {g['style']} | {m['n']} | {m['accuracy']:.1%} | {m['mean_confidence']:.1%} | {m['overconfidence']:+.1%} | "
                 f"{_f(m['brier'])}{_ci(m, 'brier')} | {_f(m['brier_skill'], 2)} | {_f(m['ece'])}{_ci(m, 'ece')} | {_f(m['auroc'], 2)} | {g['format_failures']}/{g['runs']} |")
    for g in rep["groups"]:
        m = g["metrics"]
        if not m["n"]:
            continue
        L += ["", f"## {g['model']} / {g['style']}", "", "| Confidence bin | n | Mean conf. | Accuracy |", "|---|---|---|---|"]
        L += [f"| {b['lo']:.0%}-{b['hi']:.0%} | {b['n']} | {_f(b['mean_confidence'])} | {_f(b['accuracy'])} |" for b in m["bins"] if b["n"]]
        L += ["", "| Category | n | Accuracy | Mean conf. |", "|---|---|---|---|"]
        L += [f"| {k} | {v['n']} | {v['accuracy']:.0%} | {v['mean_confidence']:.0%} |" for k, v in g["by_category"].items()]
        if g["high_confidence_errors"]:
            L += ["", f"Wrong with confidence >= {HIGH_CONF}%: " + ", ".join(g["high_confidence_errors"])]
    return "\n".join(L + ["", "## Reading these results", "", WARNING, ""])


def reliability_svg(bins) -> str:
    """Inline SVG reliability diagram: bar height = accuracy in the bin, dot = mean confidence, diagonal = perfect."""
    W = 300
    x = lambda v: 40 + v * W
    y = lambda v: 20 + (1 - v) * W
    parts = [f'<svg viewBox="0 0 360 370" role="img" aria-label="Reliability diagram" xmlns="http://www.w3.org/2000/svg">',
             f'<rect x="40" y="20" width="{W}" height="{W}" fill="none" stroke="currentColor" opacity=".3"/>',
             f'<line x1="{x(0)}" y1="{y(0)}" x2="{x(1)}" y2="{y(1)}" stroke="currentColor" stroke-dasharray="4 4" opacity=".6"/>']
    for b in bins:
        if b["n"]:
            w = (b["hi"] - b["lo"]) * W * 0.8
            cx = x((b["lo"] + b["hi"]) / 2)
            parts.append(f'<rect x="{cx - w / 2:.1f}" y="{y(b["accuracy"]):.1f}" width="{w:.1f}" height="{b["accuracy"] * W:.1f}" fill="#5e9bea" opacity=".75"/>')
            parts.append(f'<circle cx="{x(b["mean_confidence"]):.1f}" cy="{y(b["accuracy"]):.1f}" r="{3 + min(b["n"], 20) / 4:.1f}" fill="#ff9e4a" stroke="currentColor"/>')
    parts.append(f'<text x="{x(.5)}" y="362" text-anchor="middle" font-size="12" fill="currentColor">stated confidence</text>')
    parts.append(f'<text x="12" y="{y(.5)}" text-anchor="middle" font-size="12" fill="currentColor" transform="rotate(-90 12 {y(.5)})">accuracy</text></svg>')
    return "".join(parts)


def render_html(rep) -> str:
    e = html.escape
    rows, figs = "", ""
    for g in rep["groups"]:
        m = g["metrics"]
        if not m["n"]:
            continue
        rows += (f"<tr><td>{e(g['model'])}</td><td>{e(g['style'])}</td><td>{m['n']}</td><td>{m['accuracy']:.1%}</td><td>{m['mean_confidence']:.1%}</td>"
                 f"<td>{m['overconfidence']:+.1%}</td><td>{_f(m['brier'])}</td><td>{_f(m['ece'])}</td><td>{_f(m['auroc'], 2)}</td>"
                 f"<td>{g['format_failures']}/{g['runs']}</td></tr>")
        figs += f"<figure><figcaption>{e(g['model'])} / {e(g['style'])}</figcaption>{reliability_svg(m['bins'])}</figure>"
    banner = f'<p class="sim">{e(SIM_BANNER)}</p>' if rep["includes_synthetic"] else ""
    return ("<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>CALIBRATE report</title>"
            "<style>:root{color-scheme:light dark;--bg:#fff;--fg:#111;--line:#ccc;--warn:#fff3cd}@media(prefers-color-scheme:dark){:root{--bg:#10151f;--fg:#e8eefc;--line:#33415c;--warn:#3a3118}}"
            "body{font:15px/1.5 system-ui,sans-serif;max-width:1000px;margin:2rem auto;padding:0 1rem;background:var(--bg);color:var(--fg)}"
            "table{border-collapse:collapse;width:100%;display:block;overflow-x:auto}td,th{border:1px solid var(--line);padding:6px 9px;text-align:left}"
            "figure{display:inline-block;margin:1rem;max-width:360px}svg{width:100%;height:auto}.sim{background:var(--warn);padding:10px;border-radius:6px;font-weight:700}</style>"
            f"<h1>CALIBRATE report</h1>{banner}<p>Dashed line = perfect calibration. Bars = accuracy per confidence bin; dots = mean stated confidence.</p>"
            "<table><tr><th>Model</th><th>Prompt</th><th>Scored</th><th>Accuracy</th><th>Mean conf.</th><th>Gap</th><th>Brier</th><th>ECE</th><th>AUROC</th><th>Format fails</th></tr>"
            f"{rows}</table>{figs}<p>{e(WARNING)}</p></html>")


def write_report(runs_path, questions_path, questions, out_dir, include_synthetic=False, n_bins=5, boot_reps=1000):
    runs, bad = load_runs(runs_path)
    rep, per_run = build_report(runs, questions, include_synthetic, n_bins, boot_reps, sha256_file(questions_path))
    rep["unparseable_lines"] = bad
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
    (out / "report.md").write_text(render_markdown(rep), encoding="utf-8")
    (out / "report.html").write_text(render_html(rep), encoding="utf-8")
    write_csv(out / "results.csv", list(per_run[0]) if per_run else ["question_id"], per_run)
    return rep
