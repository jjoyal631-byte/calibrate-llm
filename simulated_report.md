# CALIBRATE report

> **SIMULATED RESULTS: produced by built-in mock models to demonstrate the pipeline. Never report these as real.**

Question set `90ce08358bf3...` | 5 confidence bins | excluded: 0 simulated, 0 errored, 0 unknown-question runs.

## Summary

Brier and ECE: lower is better. Skill > 0 beats always saying your average accuracy. AUROC 0.5 means confidence says nothing about correctness. Gap = mean confidence minus accuracy (positive = overconfident).

| Model | Prompt | Scored | Accuracy | Mean conf. | Gap | Brier | Skill | ECE | AUROC | Format fails |
|---|---|---|---|---|---|---|---|---|---|---|
| mock:calibrated | direct | 63 | 82.5% | 72.5% | -10.0% | 0.127 [0.090, 0.170] | 0.12 | 0.100 [0.044, 0.181] | 0.78 | 0/63 |
| mock:format_breaker | direct | 0 | | | | | | | | 63/63 |
| mock:overconfident | direct | 63 | 61.9% | 95.0% | +33.1% | 0.345 [0.245, 0.460] | -0.46 | 0.331 [0.220, 0.458] | 0.50 | 0/63 |
| mock:perfect | direct | 63 | 100.0% | 100.0% | +0.0% | 0.000 [0.000, 0.000] | n/a | 0.000 [0.000, 0.000] | n/a | 0/63 |
| mock:underconfident | direct | 63 | 87.3% | 50.0% | -37.3% | 0.250 [0.250, 0.250] | -1.26 | 0.373 [0.278, 0.452] | 0.50 | 0/63 |

## mock:calibrated / direct

| Confidence bin | n | Mean conf. | Accuracy |
|---|---|---|---|
| 40%-60% | 12 | 0.400 | 0.500 |
| 60%-80% | 25 | 0.700 | 0.840 |
| 80%-100% | 26 | 0.900 | 0.962 |

| Category | n | Accuracy | Mean conf. |
|---|---|---|---|
| arithmetic | 10 | 90% | 77% |
| calendar | 6 | 67% | 58% |
| code | 6 | 100% | 75% |
| facts | 12 | 83% | 85% |
| logic_traps | 9 | 78% | 50% |
| number_theory | 8 | 88% | 75% |
| strings | 6 | 67% | 77% |
| units | 6 | 83% | 78% |

Wrong with confidence >= 90%: CQ033

## mock:overconfident / direct

| Confidence bin | n | Mean conf. | Accuracy |
|---|---|---|---|
| 80%-100% | 63 | 0.950 | 0.619 |

| Category | n | Accuracy | Mean conf. |
|---|---|---|---|
| arithmetic | 10 | 70% | 95% |
| calendar | 6 | 83% | 95% |
| code | 6 | 83% | 95% |
| facts | 12 | 58% | 95% |
| logic_traps | 9 | 100% | 95% |
| number_theory | 8 | 12% | 95% |
| strings | 6 | 33% | 95% |
| units | 6 | 50% | 95% |

Wrong with confidence >= 90%: CQ001, CQ005, CQ009, CQ011, CQ012, CQ013, CQ014, CQ015, CQ017, CQ018, CQ020, CQ023, CQ024, CQ028, CQ031, CQ032, CQ034, CQ036, CQ052, CQ053, CQ054, CQ056, CQ057, CQ062

## mock:perfect / direct

| Confidence bin | n | Mean conf. | Accuracy |
|---|---|---|---|
| 80%-100% | 63 | 1.000 | 1.000 |

| Category | n | Accuracy | Mean conf. |
|---|---|---|---|
| arithmetic | 10 | 100% | 100% |
| calendar | 6 | 100% | 100% |
| code | 6 | 100% | 100% |
| facts | 12 | 100% | 100% |
| logic_traps | 9 | 100% | 100% |
| number_theory | 8 | 100% | 100% |
| strings | 6 | 100% | 100% |
| units | 6 | 100% | 100% |

## mock:underconfident / direct

| Confidence bin | n | Mean conf. | Accuracy |
|---|---|---|---|
| 40%-60% | 63 | 0.500 | 0.873 |

| Category | n | Accuracy | Mean conf. |
|---|---|---|---|
| arithmetic | 10 | 80% | 50% |
| calendar | 6 | 100% | 50% |
| code | 6 | 100% | 50% |
| facts | 12 | 92% | 50% |
| logic_traps | 9 | 78% | 50% |
| number_theory | 8 | 75% | 50% |
| strings | 6 | 83% | 50% |
| units | 6 | 100% | 50% |

## Reading these results

Calibration is measured on a small, fixed question set of mostly easy-to-verify questions. With a few dozen questions the intervals are wide, and good calibration here does not imply good calibration on other tasks. Do not rank models whose intervals overlap.
