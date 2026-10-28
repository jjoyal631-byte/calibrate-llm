# Changelog

## 1.0.0
- 63 verifiable questions (8 categories, 3 difficulty levels, 12 trap questions) with a recorded SHA-256; most answers computed by code.
- Deterministic parsing and grading; format failures reported, not dropped.
- Metrics: accuracy, gap, Brier (+ skill vs no-skill reference), ECE, AUROC, reliability bins, cluster bootstrap intervals.
- Runner for OpenAI-compatible endpoints: 3 prompt styles, repeats, resume, retries, dry-run, HTTPS guard.
- Report: Markdown, HTML with SVG reliability diagrams, JSON, CSV; simulated runs excluded by default.
- Simulated models with known calibration behaviour for testing.
- 48 tests, including hand-computed metrics and a local mock API server.
