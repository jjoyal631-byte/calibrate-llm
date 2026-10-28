# Methodology

## Protocol

For each (question, prompt style, repeat) the model receives a fixed system prompt and the question, and must reply with `Answer:` and `Confidence:` lines. Raw replies are stored with the question-set SHA-256, prompt version and timestamps. Parsing, grading and scoring are applied later to the stored text.

## Parsing

The **last** `Answer:` and `Confidence:` lines are used, so step-by-step reasoning that contains earlier drafts is ignored. Markdown bold, `>` quoting, `%` signs and `~` are tolerated; a JSON object with `answer` and `confidence` is a fallback. Confidence is read as a percentage; a bare decimal strictly between 0 and 1 is treated as a probability (and flagged). A bare `1` is ambiguous (1% or probability 1.0) and is rejected. Values outside 0-100 are rejected. Anything unparseable is a **format failure**, reported per model and excluded from calibration metrics.

## Grading

- **number**: the *last* number in the answer is compared with the expected value within the question's tolerance (commas, unicode minus and small number-words are handled). A reply such as "about 12 (6 x 2)" is graded on `2`; the prompt asks for the answer only.
- **text / exact**: lower-cased, leading article and punctuation stripped, whitespace removed, then compared with the answer or an alias. Deliberately strict: "No, it is not" does not match `no`.
- **text / contains**: the answer or alias must appear as a whole word.

Strictness can mark a right-but-verbose reply wrong; it affects accuracy and calibration together and is the same for every model.

## Metrics

With confidence `c` in [0,1] and outcome `y` in {0,1}:

- **Brier** = mean of `(c - y)^2`. **No-skill reference** = `p(1-p)` with `p` the observed accuracy. **Skill** = `1 - Brier / reference`.
- **ECE**: equal-width bins on [0,1] (default 5, because ~60 questions cannot fill 10 bins); `sum_b (n_b / N) * |accuracy_b - mean_confidence_b|`. Computed from unrounded values. Confidence 1.0 falls in the top bin.
- **AUROC** (Mann-Whitney form, ties count half): resolution, i.e. whether confidence separates right from wrong answers. Undefined when all answers are right or all wrong.
- **Intervals**: accuracy uses a 95% Wilson interval; Brier, ECE and accuracy also get a percentile bootstrap that resamples *questions* (with all of a question's repeats together), so repeats are not treated as independent evidence.

## Prompt styles

`direct`, `cot` (reason first, then the two lines) and `calibration_hint` (adds an explicit calibration instruction). Compare styles for the **same model** to see whether a prompt changes calibration.

## Known limitations

- 63 questions; categories hold 6-12 each, so per-category numbers are indicative only.
- Questions have single verifiable answers; calibration on subjective or open-ended tasks is not measured.
- Public questions can be memorised or trained on; treat results as a regression signal, not a certificate.
- Temperature 0 (the default) makes repeats near-identical for many APIs; use higher temperatures to study sampling variability.
- Verbalised confidence is not the same as token-probability confidence.
- Simulated models validate the pipeline only; they say nothing about real systems.
