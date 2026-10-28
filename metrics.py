"""Calibration metrics. `conf` is a probability in [0, 1]; `correct` is 0/1."""
import random
from collections import defaultdict

from .common import wilson


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def brier(conf, correct):
    return mean([(c - y) ** 2 for c, y in zip(conf, correct)])


def brier_reference(correct):
    """Brier score of always predicting the overall accuracy (the no-skill baseline)."""
    p = mean(correct)
    return None if p is None else p * (1 - p)


def _bin_stats(conf, correct, n_bins):
    """Unrounded per-bin statistics. Equal-width bins on [0,1]; confidence 1.0 belongs to the top bin."""
    acc = defaultdict(list)
    for c, y in zip(conf, correct):
        acc[min(int(c * n_bins), n_bins - 1)].append((c, y))
    out = []
    for b in range(n_bins):
        pts = acc.get(b, [])
        out.append({"lo": b / n_bins, "hi": (b + 1) / n_bins, "n": len(pts), "k": sum(y for _, y in pts),
                    "mean_confidence": mean([c for c, _ in pts]), "accuracy": mean([y for _, y in pts])})
    return out


def make_bins(conf, correct, n_bins=10):
    """Display view of the bins (rounded). Metrics are computed from the unrounded values, never from this."""
    return [{"lo": round(b["lo"], 4), "hi": round(b["hi"], 4), "n": b["n"],
             "mean_confidence": None if b["n"] == 0 else round(b["mean_confidence"], 4),
             "accuracy": None if b["n"] == 0 else round(b["accuracy"], 4), "accuracy_ci95": wilson(b["k"], b["n"])}
            for b in _bin_stats(conf, correct, n_bins)]


def ece(conf, correct, n_bins=10):
    n = len(conf)
    if not n:
        return None
    return sum(b["n"] / n * abs(b["accuracy"] - b["mean_confidence"]) for b in _bin_stats(conf, correct, n_bins) if b["n"])


def auroc(conf, correct):
    """Probability a random correct answer has higher confidence than a random wrong one (ties count half).
    0.5 = confidence carries no information about correctness; None if only one outcome is present."""
    pos = [c for c, y in zip(conf, correct) if y]
    neg = [c for c, y in zip(conf, correct) if not y]
    if not pos or not neg:
        return None
    wins = sum((p > q) + 0.5 * (p == q) for p in pos for q in neg)
    return wins / (len(pos) * len(neg))


def _point(conf, correct, n_bins):
    return {"accuracy": mean(correct), "brier": brier(conf, correct), "ece": ece(conf, correct, n_bins)}


def summarize(items, n_bins=10, boot_reps=1000, seed=12345):
    """items: list of {"qid", "conf" (0-1), "correct" (0/1)}. Bootstrap resamples whole questions (clusters),
    so repeated runs of one question are not treated as independent."""
    conf, corr = [i["conf"] for i in items], [i["correct"] for i in items]
    n = len(items)
    if not n:
        return {"n": 0}
    b, ref = brier(conf, corr), brier_reference(corr)
    out = {"n": n, "accuracy": mean(corr), "accuracy_ci95": wilson(sum(corr), n), "mean_confidence": mean(conf),
           "overconfidence": mean(conf) - mean(corr), "brier": b, "brier_reference": ref,
           "brier_skill": (1 - b / ref) if ref else None, "ece": ece(conf, corr, n_bins), "auroc": auroc(conf, corr),
           "bins": make_bins(conf, corr, n_bins)}
    by_q = defaultdict(list)
    for i in items:
        by_q[i["qid"]].append(i)
    qids, rng, boots = sorted(by_q), random.Random(seed), defaultdict(list)
    if len(qids) >= 2 and boot_reps:
        for _ in range(boot_reps):
            sample = [x for q in rng.choices(qids, k=len(qids)) for x in by_q[q]]
            c, y = [x["conf"] for x in sample], [x["correct"] for x in sample]
            for k, v in _point(c, y, n_bins).items():
                boots[k].append(v)
        for k, vs in boots.items():
            vs.sort()
            out[k + "_ci95_bootstrap"] = [round(vs[int(0.025 * len(vs))], 4), round(vs[int(0.975 * len(vs)) - 1], 4)]
    return out
