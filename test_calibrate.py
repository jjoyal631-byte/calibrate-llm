import csv
import io
import json
import os
import tempfile
import threading
import unittest
from collections import Counter
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

from calibrate import cli, grading, metrics, parsing, prompts, providers, report, runner
from calibrate.common import QUESTIONS_PATH, ROOT, csv_safe, recorded_hash, sha256_file, wilson, write_csv
from calibrate.questions import CATEGORIES, check_hash, load_questions, validate

QS = load_questions()
BY_ID = {q["id"]: q for q in QS}


def q(**over):
    base = {"id": "CQ900", "category": "arithmetic", "difficulty": "easy", "question": "What is 1+1?", "answer": 2,
            "answer_type": "number", "tolerance": 0, "aliases": [], "match": "exact"}
    base.update(over)
    return base


class QuestionSetTests(unittest.TestCase):
    def test_valid_hash_and_size(self):
        self.assertEqual(validate(QS), [])
        self.assertEqual(check_hash(), [])
        self.assertEqual(recorded_hash(), sha256_file(QUESTIONS_PATH))
        self.assertEqual(len(QS), 63)

    def test_coverage(self):
        self.assertEqual(set(Counter(x["category"] for x in QS)), set(CATEGORIES))
        d = Counter(x["difficulty"] for x in QS)
        self.assertTrue(all(d[k] >= 10 for k in ("easy", "medium", "hard")), d)

    def test_every_question_self_consistent_end_to_end(self):
        """A perfect reply parses and grades right; a wrong one grades wrong; aliases grade right."""
        for x in QS:
            p = parsing.parse_response(providers.mock_reply("perfect", x, "direct"))
            self.assertIs(grading.grade(x, p["answer"]), True, x["id"])
            self.assertIs(grading.grade(x, grading.wrong_answer(x)), False, x["id"])
            self.assertTrue(all(grading.grade(x, a) for a in x["aliases"]))

    def test_independently_recomputed_answers(self):
        """Spot-check computed answers against values worked out by hand, not by the generator."""
        expect = {"CQ001": 391, "CQ006": 1048576, "CQ011": 211, "CQ012": 15, "CQ013": 55, "CQ026": 29,
                  "CQ027": "2026-04-11", "CQ031": 3, "CQ037": 5, "CQ039": 47, "CQ042": 11, "CQ062": -4}
        for qid, v in expect.items():
            self.assertEqual(BY_ID[qid]["answer"], v, qid)

    def test_validator_rejects_bad_questions(self):
        bad = [q(id="X"), q(category="art"), q(difficulty="insane"), q(answer_type="image"), q(answer="two"), q(answer=True),
               q(tolerance=-1), q(aliases="x"), q(question=" "), q(match="fuzzy"), q(answer_type="text", answer=" "),
               q(answer_type="text", answer="x", aliases=["zzz-unknown"]), "x", None]
        for b in bad:
            self.assertTrue(validate([b]), b)
        self.assertIn("duplicate id", " ".join(validate([q(), q(question="other")])))
        self.assertIn("duplicate question", " ".join(validate([q(), q(id="CQ901")])))
        self.assertTrue(validate([]))

    def test_hash_change_detected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "q.json"
            p.write_bytes(QUESTIONS_PATH.read_bytes() + b"\n")
            self.assertTrue(check_hash(p))


class GradingTests(unittest.TestCase):
    def test_numbers(self):
        g = lambda ans, a, **k: grading.grade(q(answer=a, **k), ans)
        self.assertTrue(g("391", 391)); self.assertTrue(g("1,048,576", 1048576)); self.assertTrue(g("-4", -4))
        self.assertTrue(g("\u22124", -4), "unicode minus"); self.assertTrue(g("5 cents", 5))
        self.assertTrue(g("2^20 = 1048576", 1048576), "last number wins")
        self.assertTrue(g("twelve", 12)); self.assertTrue(g("**36**", 36)); self.assertTrue(g("0.875", 0.875))
        self.assertFalse(g("390", 391)); self.assertFalse(g("4", -4))
        self.assertTrue(g("37.04", 37.0, tolerance=0.05)); self.assertFalse(g("37.1", 37.0, tolerance=0.05))
        self.assertIsNone(g("no idea", 5)); self.assertIsNone(grading.grade(q(), None))

    def test_text_exact(self):
        t = lambda ans, a="no", **k: grading.grade(q(answer_type="text", answer=a, **k), ans)
        self.assertTrue(t("No.")); self.assertTrue(t(" **no** ")); self.assertTrue(t("NO"))
        self.assertFalse(t("No, 2100 is not leap"), "exact match is strict by design")
        self.assertTrue(t("[3,  2, 1]", "[3, 2, 1]")); self.assertTrue(t("The Mary", "mary"))
        self.assertTrue(t("2nd", "second", aliases=["2nd"]))

    def test_text_contains_uses_word_boundaries(self):
        t = lambda ans, **k: grading.grade(q(answer_type="text", answer="pacific", match="contains", **k), ans)
        self.assertTrue(t("The Pacific Ocean")); self.assertTrue(t("pacific.")); self.assertFalse(t("Unpacific")); self.assertFalse(t("Atlantic"))
        co2 = q(answer_type="text", answer="carbon dioxide", aliases=["co2"], match="contains")
        self.assertTrue(grading.grade(co2, "CO2")); self.assertTrue(grading.grade(co2, "carbon dioxide (CO2)"))


class ParsingTests(unittest.TestCase):
    def test_standard_and_markdown(self):
        for text in ("Answer: 391\nConfidence: 95", "**Answer:** 391\n**Confidence:** 95%", "answer - 391\nconfidence - 95 %",
                     "> Answer: 391\n> Confidence: ~95%", "Answer: 391\nConfidence: 95/100"):
            p = parsing.parse_response(text)
            self.assertEqual((p["answer"], p["confidence"], p["error"]), ("391", 95.0, None), text)

    def test_last_occurrence_wins_for_reasoning(self):
        p = parsing.parse_response("Draft\nAnswer: 5\nConfidence: 10\nHmm, recheck.\nAnswer: 7\nConfidence: 60")
        self.assertEqual((p["answer"], p["confidence"]), ("7", 60.0))

    def test_confidence_edge_cases(self):
        c = lambda s: parsing.parse_response("Answer: x\nConfidence: " + s)
        self.assertEqual(c("0")["confidence"], 0.0); self.assertEqual(c("100")["confidence"], 100.0)
        self.assertEqual(c("0.85")["confidence"], 85.0); self.assertEqual(c("0.85")["flags"], ["fraction_converted"])
        self.assertEqual(c("1%")["confidence"], 1.0)
        for bad in ("1", "101", "250"):
            self.assertIsNone(c(bad)["confidence"], bad); self.assertTrue(c(bad)["error"])

    def test_missing_pieces_and_json_fallback(self):
        self.assertEqual(parsing.parse_response("It is 5.")["error"], "no 'Answer:' line")
        self.assertEqual(parsing.parse_response("Answer: 5")["error"], "no 'Confidence:' line")
        p = parsing.parse_response('Here: {"answer": "Canberra", "confidence": 90}')
        self.assertEqual((p["answer"], p["confidence"], p["error"]), ("Canberra", 90.0, None))
        self.assertIsNone(parsing.parse_response('{"answer": "x", "confidence": true}')["confidence"])
        for junk in ("", None, "Answer:", "Confidence: abc", "\x00\x01"):
            parsing.parse_response(junk)  # must never raise


class MetricTests(unittest.TestCase):
    def test_brier_hand_computed(self):
        self.assertAlmostEqual(metrics.brier([0.9, 0.5], [1, 0]), 0.13)
        self.assertEqual(metrics.brier([1, 0], [1, 0]), 0)
        self.assertEqual(metrics.brier([1, 0], [0, 1]), 1)

    def test_ece_hand_computed(self):
        # bin 9: 2 items, mean conf .9, acc .5 -> .4 * 2/4 ; bin 1: 2 items, conf .1, acc 0 -> .1 * 2/4
        self.assertAlmostEqual(metrics.ece([.9, .9, .1, .1], [1, 0, 0, 0], 10), 0.25)
        self.assertEqual(metrics.ece([.8, .8, .8, .8, .8], [1, 1, 1, 1, 0], 10), 0.0)
        self.assertIsNone(metrics.ece([], []))

    def test_bin_edges(self):
        b = metrics.make_bins([0.0, 1.0, 0.5, 0.2], [0, 1, 1, 0], 5)
        self.assertEqual([x["n"] for x in b], [1, 1, 1, 0, 1])  # 0.2 -> bin 1, 0.5 -> bin 2, 1.0 -> top bin
        self.assertEqual(b[4]["accuracy"], 1.0)

    def test_auroc(self):
        self.assertEqual(metrics.auroc([.9, .8, .3, .2], [1, 1, 0, 0]), 1.0)
        self.assertEqual(metrics.auroc([.9, .8, .3, .2], [0, 0, 1, 1]), 0.0)
        self.assertEqual(metrics.auroc([.7, .7, .7, .7], [1, 0, 1, 0]), 0.5)
        self.assertAlmostEqual(metrics.auroc([.9, .4, .6, .2], [1, 1, 0, 0]), 0.75)  # pairs: (.9>.6)(.9>.2)(.4<.6)(.4>.2) = 3/4
        self.assertIsNone(metrics.auroc([.9, .8], [1, 1]))

    def test_brier_skill_zero_for_climatology(self):
        s = metrics.summarize([{"qid": f"q{i}", "conf": .75, "correct": int(i < 3)} for i in range(4)], boot_reps=0)
        self.assertAlmostEqual(s["brier"], s["brier_reference"]); self.assertAlmostEqual(s["brier_skill"], 0.0)
        self.assertAlmostEqual(s["brier_reference"], 0.1875)

    def test_summary_fields_and_overconfidence_sign(self):
        s = metrics.summarize([{"qid": f"q{i}", "conf": .95, "correct": int(i < 6)} for i in range(10)], n_bins=5, boot_reps=0)
        self.assertAlmostEqual(s["accuracy"], .6); self.assertAlmostEqual(s["overconfidence"], .35)
        self.assertAlmostEqual(s["ece"], .35); self.assertEqual(s["accuracy_ci95"], wilson(6, 10))
        self.assertEqual(metrics.summarize([]), {"n": 0})

    def test_cluster_bootstrap_is_deterministic_and_brackets_estimate(self):
        items = [{"qid": f"q{i % 8}", "conf": .5 + (i % 5) / 10, "correct": int(i % 3 != 0)} for i in range(24)]  # 3 repeats per question
        a, b = metrics.summarize(items, 5, 300), metrics.summarize(items, 5, 300)
        self.assertEqual(a, b)
        for k in ("accuracy", "brier", "ece"):
            lo, hi = a[k + "_ci95_bootstrap"]
            self.assertLessEqual(lo, hi)
        self.assertLessEqual(a["brier_ci95_bootstrap"][0], a["brier"] + 1e-9); self.assertGreaterEqual(a["brier_ci95_bootstrap"][1], a["brier"] - 1e-9)
        self.assertNotIn("brier_ci95_bootstrap", metrics.summarize([{"qid": "q", "conf": .5, "correct": 1}] * 3, 5, 300))  # one cluster


class SimulatedPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(); cls.runs = Path(cls.tmp.name) / "runs.jsonl"
        for pol in providers.MOCK_POLICIES:
            runner.run_experiment(providers.MockProvider(pol), QS, ["direct", "cot"], 1, cls.runs, QUESTIONS_PATH, log=lambda *_: None)
        cls.rows = [json.loads(l) for l in cls.runs.read_text().splitlines()]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def g(self, model, style="direct", **kw):
        rep, _ = report.build_report(self.rows, QS, include_synthetic=True, boot_reps=0, **kw)
        return next(x for x in rep["groups"] if (x["model"], x["style"]) == (model, style))

    def test_perfect(self):
        m = self.g("mock:perfect")["metrics"]
        self.assertEqual((m["accuracy"], m["brier"], m["ece"], m["auroc"]), (1.0, 0.0, 0.0, None))

    def test_overconfident_matches_hand_calculation(self):
        m = self.g("mock:overconfident")["metrics"]
        k = round(m["accuracy"] * 63)
        self.assertAlmostEqual(m["brier"], (k * 0.05 ** 2 + (63 - k) * 0.95 ** 2) / 63)
        self.assertAlmostEqual(m["ece"], 0.95 - m["accuracy"], places=12, msg="ECE must use unrounded bin values")
        self.assertEqual(m["auroc"], 0.5)
        self.assertGreater(m["overconfidence"], 0.3)

    def test_underconfident_has_negative_gap_and_brier_quarter(self):
        m = self.g("mock:underconfident")["metrics"]
        self.assertAlmostEqual(m["brier"], 0.25); self.assertLess(m["overconfidence"], -0.3)

    def test_calibrated_beats_the_miscalibrated_models_and_has_resolution(self):
        c, o, u = (self.g(f"mock:{p}")["metrics"] for p in ("calibrated", "overconfident", "underconfident"))
        self.assertLess(c["ece"], o["ece"]); self.assertLess(c["ece"], u["ece"]); self.assertLess(c["brier"], o["brier"])
        self.assertGreater(c["auroc"], 0.65); self.assertGreater(c["brier_skill"], 0.0)

    def test_format_breaker_scores_nothing_and_is_reported(self):
        g = self.g("mock:format_breaker")
        self.assertEqual((g["scored"], g["format_failures"], g["format_failure_rate"]), (0, 63, 1.0))
        self.assertIn("0 |", report.render_markdown({**report.build_report(self.rows, QS, True, boot_reps=0)[0]}))

    def test_cot_prefix_is_ignored_by_parser(self):
        a, b = self.g("mock:calibrated", "direct")["metrics"], self.g("mock:calibrated", "cot")["metrics"]
        self.assertEqual((a["accuracy"], a["brier"]), (b["accuracy"], b["brier"]))

    def test_breakdowns_add_up(self):
        g = self.g("mock:calibrated")
        self.assertEqual(sum(v["n"] for v in g["by_category"].values()), 63); self.assertEqual(sum(v["n"] for v in g["by_difficulty"].values()), 63)
        self.assertGreater(g["by_difficulty"]["easy"]["accuracy"], g["by_difficulty"]["hard"]["accuracy"])

    def test_high_confidence_errors(self):
        ids = self.g("mock:overconfident")["high_confidence_errors"]
        self.assertTrue(ids and all(i in BY_ID for i in ids)); self.assertEqual(self.g("mock:perfect")["high_confidence_errors"], [])


class ReportTests(unittest.TestCase):
    def rows(self, text, **kw):
        return {"question_id": "CQ001", "style": "direct", "model_requested": "m", "text": text, **kw}

    def test_synthetic_excluded_by_default_with_banner_when_included(self):
        r = [self.rows("Answer: 391\nConfidence: 90", synthetic=True)]
        rep, per = report.build_report(r, QS)
        self.assertEqual((rep["groups"], per, rep["excluded"]["synthetic"]), ([], [], 1))
        self.assertIn("No scored runs", report.render_markdown(rep))
        rep, _ = report.build_report(r, QS, include_synthetic=True)
        self.assertIn("SIMULATED RESULTS", report.render_markdown(rep)); self.assertIn("SIMULATED RESULTS", report.render_html(rep))

    def test_errors_unknown_questions_and_foreign_hash(self):
        r = [self.rows("", error="boom"), self.rows("Answer: 1\nConfidence: 50", question_id="CQ999"),
             self.rows("Answer: 391\nConfidence: 90", question_set_sha256="other")]
        rep, _ = report.build_report(r, QS, questions_sha="current")
        self.assertEqual(rep["excluded"], {"synthetic": 0, "errors": 1, "unknown_question": 1})
        self.assertEqual((rep["runs_from_other_question_hash"], rep["groups"][0]["errors"]), (1, 1))
        self.assertIn("different question-set hash", report.render_markdown(rep))

    def test_unparseable_ungradable_counts_as_format_failure(self):
        r = [self.rows("The answer is 391."), self.rows("Answer: hmm\nConfidence: 50"), self.rows("Answer: 391\nConfidence: 1"),
             self.rows("Answer: 391\nConfidence: 80")]
        rep, per = report.build_report(r, QS, boot_reps=0)
        g = rep["groups"][0]
        self.assertEqual((g["runs"], g["scored"], g["format_failures"]), (4, 1, 3))
        self.assertEqual(g["metrics"]["n"], 1); self.assertTrue(any("ambiguous" in p["parse_error"] for p in per))

    def test_end_to_end_numbers_hand_computed(self):
        r = [self.rows("Answer: 391\nConfidence: 80"), self.rows("Answer: 5\nConfidence: 80", question_id="CQ002"),
             self.rows("Answer: 12\nConfidence: 80", question_id="CQ002", repeat=1), self.rows("Answer: 2\nConfidence: 80", question_id="CQ003")]
        rep, _ = report.build_report(r, QS, boot_reps=0)
        m = rep["groups"][0]["metrics"]   # CQ001 right, CQ002 wrong then right, CQ003 wrong => 2/4 correct
        self.assertEqual((m["n"], m["accuracy"]), (4, 0.5)); self.assertAlmostEqual(m["brier"], .5 * .2 ** 2 + .5 * .8 ** 2)

    def test_html_escapes_and_svg_has_no_user_text(self):
        evil = "<script>alert(1)</script>"
        rep, _ = report.build_report([self.rows("Answer: 391\nConfidence: 90", model_requested=evil)], QS, boot_reps=0)
        h = report.render_html(rep)
        self.assertNotIn("<script>alert", h); self.assertIn("&lt;script&gt;", h); self.assertIn("<svg", h)
        self.assertNotIn(evil, report.reliability_svg(rep["groups"][0]["metrics"]["bins"]))

    def test_csv_neutralises_formulas(self):
        rep, per = report.build_report([self.rows("Answer: =cmd|' /C calc'!A0\nConfidence: 50")], QS, boot_reps=0)
        with tempfile.TemporaryDirectory() as d:
            write_csv(Path(d) / "r.csv", list(per[0]), per)
            with (Path(d) / "r.csv").open(encoding="utf-8-sig", newline="") as f:
                self.assertTrue(next(csv.DictReader(f))["answer"].startswith("'="))
        self.assertTrue(csv_safe("@x").startswith("'"))

    def test_write_report_files_and_bins_option(self):
        with tempfile.TemporaryDirectory() as d:
            runs = Path(d) / "r.jsonl"
            runner.run_experiment(providers.MockProvider("calibrated"), QS[:20], ["direct"], 2, runs, QUESTIONS_PATH, log=lambda *_: None)
            rep = report.write_report(runs, QUESTIONS_PATH, QS, Path(d) / "o", include_synthetic=True, n_bins=10, boot_reps=50)
            self.assertEqual(len(rep["groups"][0]["metrics"]["bins"]), 10)
            for f in ("summary.json", "report.md", "report.html", "results.csv"):
                self.assertGreater((Path(d) / "o" / f).stat().st_size, 0)
            self.assertIn("brier_ci95_bootstrap", rep["groups"][0]["metrics"])


class MockAPI:
    def __init__(self, script=(), reply=None):
        self.script, self.requests, self.reply = list(script), [], reply
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append({"auth": self.headers.get("Authorization"), "body": body})
                if outer.script:
                    status, payload = outer.script.pop(0)
                else:
                    status, payload = 200, {"id": "r", "model": "http-model-1", "choices": [{"message": {"content": outer.reply(body["messages"][1]["content"])}}]}
                data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                self.send_response(status); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

            def log_message(self, *a):
                pass
        self.server = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown(); self.server.server_close()


def ok(text="Answer: 391\nConfidence: 80"):
    return {"id": "r", "model": "m", "choices": [{"message": {"content": text}}]}


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.out = Path(self.tmp.name) / "runs.jsonl"; self.apis = []

    def tearDown(self):
        [a.close() for a in self.apis]; self.tmp.cleanup()

    def api(self, script=(), reply=None):
        a = MockAPI(script, reply or (lambda _: "Answer: 1\nConfidence: 50")); self.apis.append(a); return a

    def prov(self, a, **kw):
        return providers.OpenAICompatible(a.url, "sk-secret-key", "test-model", backoff=0, sleep=lambda s: None, **kw)

    def lines(self):
        return [json.loads(l) for l in self.out.read_text(encoding="utf-8").splitlines()]

    def go(self, p, ids, styles=("direct",), repeats=1, **kw):
        return runner.run_experiment(p, [BY_ID[i] for i in ids], list(styles), repeats, self.out, QUESTIONS_PATH, log=lambda *_: None, **kw)

    def test_provenance_and_key_hygiene(self):
        a = self.api(); self.assertEqual(self.go(self.prov(a), ["CQ001"]), {"collected": 1, "skipped": 0, "failed": 0})
        r = self.lines()[0]
        self.assertEqual((r["question_id"], r["model_requested"], r["model_returned"], r["synthetic"]), ("CQ001", "test-model", "http-model-1", False))
        self.assertEqual(r["question_set_sha256"], sha256_file(QUESTIONS_PATH)); self.assertEqual(a.requests[0]["auth"], "Bearer sk-secret-key")
        self.assertNotIn("tools", a.requests[0]["body"]); self.assertNotIn("sk-secret-key", self.out.read_text(encoding="utf-8"))
        self.assertEqual(a.requests[0]["body"]["messages"][1]["content"], BY_ID["CQ001"]["question"])

    def test_matrix_resume_and_no_resume(self):
        a = self.api(); p = self.prov(a)
        self.go(p, ["CQ001", "CQ002"], ("direct", "cot"), repeats=2); self.assertEqual(len(a.requests), 8)
        n = self.go(p, ["CQ001", "CQ002", "CQ003"], ("direct", "cot"), repeats=2); self.assertEqual((n["collected"], n["skipped"]), (4, 8))
        self.go(p, ["CQ001"], resume=False); self.assertEqual(len(self.lines()), 13)

    def test_retries_hard_failure_and_malformed(self):
        a = self.api([(429, {}), (503, {}), (200, ok())]); self.assertEqual(self.go(self.prov(a), ["CQ001"])["collected"], 1); self.assertEqual(self.lines()[0]["attempts"], 3)
        b = self.api([(400, {"error": "bad"}), (200, ok())]); n = self.go(self.prov(b), ["CQ002"])
        self.assertEqual((n["failed"], len(b.requests)), (1, 1)); self.assertIn("HTTP 400", self.lines()[-1]["error"])
        c = self.api([(200, {"choices": []}), (200, ok(None)), (200, b"not json"), (200, ok("  "))])
        self.assertEqual(self.go(self.prov(c, retries=0), ["CQ003", "CQ004", "CQ005", "CQ006"])["failed"], 4)

    def test_http_end_to_end_to_report(self):
        wrong = {BY_ID[i]["question"] for i in ("CQ002", "CQ004", "CQ006")}
        reply = lambda text: "Answer: " + ("zzz" if text in wrong else "?") + "\nConfidence: 80"
        ids = [f"CQ00{i}" for i in range(1, 7)]
        right = lambda x: grading.format_number(BY_ID[x]["answer"])
        a = self.api(reply=lambda text: ("Answer: 0\nConfidence: 80" if text in wrong else f"Answer: {right(next(i for i in ids if BY_ID[i]['question'] == text))}\nConfidence: 80"))
        self.go(self.prov(a), ids)
        rep, _ = report.build_report([json.loads(l) for l in self.out.read_text().splitlines()], QS, boot_reps=0)
        m = rep["groups"][0]["metrics"]
        self.assertEqual((m["n"], m["accuracy"], rep["includes_synthetic"]), (6, 0.5, False))
        self.assertAlmostEqual(m["brier"], .5 * .2 ** 2 + .5 * .8 ** 2)

    def test_mock_provider_flagged_synthetic(self):
        self.go(providers.MockProvider("perfect"), ["CQ001"]); self.assertTrue(self.lines()[0]["synthetic"])


class ProviderTests(unittest.TestCase):
    def test_https_guard(self):
        with self.assertRaises(SystemExit):
            providers.OpenAICompatible("http://api.example.com/v1", "k", "m")
        providers.OpenAICompatible("http://127.0.0.1:1/v1", "k", "m"); providers.OpenAICompatible("https://api.example.com/v1", "k", "m")

    def test_parse_chat_response(self):
        self.assertEqual(providers.parse_chat_response(ok("hi")), "hi")
        self.assertEqual(providers.parse_chat_response({"choices": [{"message": {"content": [{"text": "a"}, {"text": "b"}]}}]}), "ab")
        for bad in ({}, {"choices": []}, ok(None), ok(" ")):
            with self.assertRaises(ValueError):
                providers.parse_chat_response(bad)

    def test_mock_unknown_policy_and_determinism(self):
        with self.assertRaises(SystemExit):
            providers.MockProvider("evil")
        x = BY_ID["CQ011"]
        self.assertEqual(providers.mock_reply("calibrated", x, "direct"), providers.mock_reply("calibrated", x, "direct"))


class PromptTests(unittest.TestCase):
    def test_styles(self):
        x = BY_ID["CQ001"]
        for s in prompts.STYLES:
            m = prompts.build_messages(x, s)
            self.assertIn("Confidence:", m[0]["content"]); self.assertEqual(m[1]["content"], x["question"])
        self.assertIn("well calibrated", prompts.build_messages(x, "calibration_hint")[0]["content"])
        self.assertNotIn("well calibrated", prompts.build_messages(x, "direct")[0]["content"])
        with self.assertRaises(ValueError):
            prompts.build_messages(x, "nope")


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli.main(list(args))
        return code, out.getvalue()

    def test_list_validate_prompt(self):
        self.assertIn("63 questions", self.run_cli("list")[1]); self.assertEqual(self.run_cli("validate", "--check-hash")[0], 0)
        self.assertIn("Confidence:", self.run_cli("prompt", "CQ001", "--style", "cot")[1])
        with self.assertRaises(SystemExit):
            self.run_cli("prompt", "CQ999")

    def test_dry_run_and_bad_args(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            code, out = self.run_cli("run", "--dry-run", "--question-ids", "CQ001,CQ002", "--styles", "direct,cot")
            self.assertEqual(code, 0); self.assertIn("2 questions x 2 styles", out)
            for args in (("run", "--styles", "bogus", "--dry-run"), ("run", "--repeats", "0", "--dry-run"), ("run", "--question-ids", "CQ999", "--dry-run"),
                         ("run", "--provider", "weird"), ("run", "--provider", "openai"), ("run", "--provider", "mock:evil")):
                with self.assertRaises(SystemExit, msg=args):
                    self.run_cli(*args)

    def test_mock_run_report_resume(self):
        with tempfile.TemporaryDirectory() as d:
            runs, outdir = str(Path(d) / "r.jsonl"), str(Path(d) / "rep")
            self.assertEqual(self.run_cli("run", "--provider", "mock:calibrated", "--limit", "12", "--out", runs)[0], 0)
            self.assertIn("All runs were simulated", self.run_cli("report", "--runs", runs, "--out", outdir)[1])
            self.assertIn("1 model/prompt groups", self.run_cli("report", "--runs", runs, "--out", outdir, "--include-synthetic", "--boot", "0")[1])
            self.assertIn("12 skipped", self.run_cli("run", "--provider", "mock:calibrated", "--limit", "12", "--out", runs)[1])

    def test_example_report_is_clearly_simulated(self):
        self.assertIn("SIMULATED RESULTS", (ROOT / "examples" / "simulated_report.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
