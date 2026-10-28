# Contributing

## Adding a question

Append an object to `data/questions.json` with the next ID (`CQnnn`):

| Field | Notes |
|---|---|
| `category`, `difficulty` | from the lists in `calibrate/questions.py` |
| `question` | include the answer-format instruction ("Answer with a number only.") |
| `answer_type` | `number` or `text` |
| `answer` | **compute it with code where possible**, and double-check hand-typed facts; the answer must be stable over time and uncontroversial |
| `tolerance` | numeric tolerance (0 = exact) |
| `aliases`, `match` | alternative accepted answers; `exact` or `contains` (whole word) |

The validator requires that each question grades its own answer and aliases as correct and the built-in wrong answer as wrong. Then run:

```bash
python -m calibrate validate
python -m calibrate validate --write-hash
python -m unittest discover -s tests
```

## Adding a provider or metric

Providers implement `chat(messages, ctx)` and set `kind` / `synthetic`. New metrics need a test with a value computed by hand, independent of the implementation.

## Results

Never commit API keys. State the model version, date, question-set hash and prompt style with any published numbers.
