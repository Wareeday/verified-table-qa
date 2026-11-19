# Verified Table QA - run report

- Dataset: `wikitq`  |  Model: `gemini-3.5-flash-lite`  |  Questions: **100**
- Queries per question (K): **3**  |  Confidence threshold: **0.66**  |  Seed: 7

## Headline numbers (95% bootstrap confidence intervals)

| Method | Accuracy | 95% CI |
|---|---|---|
| B. SQL, one query | 59.0% | 50.0% to 68.0% |
| C. SQL, majority vote of K queries (answers everything) | 62.0% | 53.0% to 71.0% |
| D. Vote + abstain: accuracy on the questions it answered | 68.6% | 58.7% to 77.9% |
| D. Coverage (share of questions answered) | 86.0% | 79.0% to 93.0% |

Paired differences (same questions, so this is the fair comparison):

- Voting vs one query (C minus B): **+3.0 points**, 95% CI +0.0 to +7.0

If a confidence interval for a difference includes 0, you cannot say the two methods differ at this sample size.

## Does the confidence score separate right from wrong?

- AUROC of confidence vs correctness: **0.68** (95% CI 0.58 to 0.76). 0.50 means the score is useless; 1.00 means perfect.
- Accuracy on answered questions: 68.6%. Accuracy on the questions it refused: 21.4%.

## Accuracy vs coverage (every possible threshold)

| confidence >= | coverage | accuracy on answered |
|---|---|---|
| 1.00 | 73.0% | 72.6% |
| 0.67 | 86.0% | 68.6% |
| 0.50 | 91.0% | 65.9% |
| 0.33 | 96.0% | 64.6% |
| 0.00 | 100.0% | 62.0% |

![coverage curve](coverage_curve.png)

## Why the single query was wrong (automatic first-pass labels)

| Label | Count |
|---|---|
| wrong_value | 27 |
| empty_result | 7 |
| wrong_number_of_values | 7 |

These labels are automatic and rough. Open `failures_to_audit.csv`, read each failure and write your own label in the `your_label` column. That manual taxonomy is the most valuable part of this project.

Sanity-check flags raised on the voted answers: no_valid_query=4, type_mismatch=4, ungrounded=1

## Read this before you quote any number

- Method D answers fewer questions, so its accuracy is NOT comparable with A, B and C. Always quote accuracy together with coverage.
- With a small number of questions the confidence intervals are wide. Say so.
- Answers are compared as sets of values after simple normalisation (see `vtqa/scoring.py`).