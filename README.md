# CALIBRATE

Does an AI's stated confidence match how often it is actually right? CALIBRATE asks a model questions with **verifiable answers**, has it state a confidence for each, grades the answers automatically, and reports calibration with reliability diagrams, Brier score, expected calibration error (ECE) and AUROC. Standard library only; Python 3.10+.

## What is inside

- **63 questions** (`data/questions.json`) across 8 categories (arithmetic, number theory, units, calendar, strings, logic traps, facts, code), easy to hard. Most answers are **computed by code**, not typed from memory; the rest are stable facts. 12 are classic trap questions that tempt confident wrong answers.
- **Deterministic grading**: numeric tolerance, normalized text, aliases. No human or LLM judge.
- **A runner** for any OpenAI-compatible chat endpoint, with 3 prompt styles (`direct`, `cot`, `calibration_hint`), repeats, resume, retries, `--dry-run` and an HTTPS guard.
- **A report generator** (Markdown, HTML with inline SVG reliability diagrams, JSON, CSV) that grades *stored* raw replies, so grading rules can improve without re-calling a model. Question-level (cluster) bootstrap intervals.
- **Simulated models** with known calibration behaviour (`perfect`, `calibrated`, `overconfident`, `underconfident`, `format_breaker`) used to test the metrics. Their results are flagged and excluded from reports by default.
- **48 tests**, including hand-computed metric values and a local mock API server.

## Quick start

```bash
python -m calibrate list
python -m calibrate validate --check-hash
python -m calibrate prompt CQ011 --style calibration_hint     # see exactly what a model receives

# free, offline demo with a simulated model
python -m calibrate run --provider mock:overconfident
python -m calibrate report --include-synthetic                # simulated numbers: demonstration only
```

### Testing a real model

```bash
export OPENAI_BASE_URL=https://api.example.com/v1     # any OpenAI-compatible endpoint
export OPENAI_API_KEY=...                              # never commit this
export OPENAI_MODEL=your-model-name
python -m calibrate run --dry-run --limit 3
python -m calibrate run --limit 10                     # start small: network use may cost money
python -m calibrate run --styles direct,cot,calibration_hint --repeats 3
python -m calibrate report                             # results/report/{report.md,report.html,summary.json,results.csv}
```

Models are asked to reply with `Answer: ...` and `Confidence: <0-100>`. Replies that cannot be parsed are counted as **format failures** and shown in the report, never silently dropped.

## Reading a report

| Metric | Meaning | Better |
|---|---|---|
| **Accuracy** | Share of graded answers that were correct | higher |
| **Gap** | Mean confidence minus accuracy. Positive = overconfident | near 0 |
| **Brier** | Mean squared error of confidence as a probability | lower |
| **Skill** | `1 - Brier / Brier(always say your average accuracy)`; below 0 is worse than that no-skill baseline | higher |
| **ECE** | Weighted average gap between confidence and accuracy across confidence bins | lower |
| **AUROC** | Chance that a correct answer carries higher confidence than a wrong one; 0.5 means confidence says nothing about correctness | higher |

A model can have a perfect-looking gap and still be useless: one that always says 70% and is right 70% of the time has ECE near 0 but AUROC 0.5. Read the metrics together.

## Important limits

Measured on a small public question set of mostly easy-to-verify questions. Famous puzzles may be memorised by models, which affects both accuracy and confidence. With ~60 questions intervals are wide and ECE is noisy (see the bootstrap intervals). Good calibration here does not imply calibration on open-ended or domain tasks. See [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md).

## Adding questions

See [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md). After editing `data/questions.json` run `python -m calibrate validate --write-hash`; runs are only comparable under the same hash.

## Tests

```bash
python -m unittest discover -s tests -v
```

License: MIT (see `LICENSE`). Example simulated output: `examples/simulated_report.md`.
