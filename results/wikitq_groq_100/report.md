# Verified Table QA - run report

- Dataset: `wikitq`  |  Model: `openai/gpt-oss-120b`  |  Questions: **100**
- Queries per question (K): **3**  |  Confidence threshold: **0.66**  |  Seed: 7

## Headline numbers (95% bootstrap confidence intervals)

| Method | Accuracy | 95% CI |
|---|---|---|
| B. SQL, one query | 63.0% | 54.0% to 72.0% |
| C. SQL, majority vote of K queries (answers everything) | 64.0% | 55.0% to 73.0% |
| D. Vote + abstain: accuracy on the questions it answered | 74.4% | 65.1% to 83.1% |
| D. Coverage (share of questions answered) | 82.0% | 74.0% to 89.0% |

Paired differences (same questions, so this is the fair comparison):

- Voting vs one query (C minus B): **+1.0 points**, 95% CI -2.0 to +4.0

If a confidence interval for a difference includes 0, you cannot say the two methods differ at this sample size.

## Does the confidence score separate right from wrong?

- AUROC of confidence vs correctness: **0.74** (95% CI 0.64 to 0.83). 0.50 means the score is useless; 1.00 means perfect.
- Accuracy on answered questions: 74.4%. Accuracy on the questions it refused: 16.7%.

## Accuracy vs coverage (every possible threshold)

| confidence >= | coverage | accuracy on answered |
|---|---|---|
| 1.00 | 69.0% | 78.3% |
| 0.67 | 82.0% | 74.4% |
| 0.50 | 85.0% | 74.1% |
| 0.33 | 94.0% | 68.1% |
| 0.00 | 100.0% | 64.0% |

![coverage curve](coverage_curve.png)

## Why the single query was wrong (automatic first-pass labels)

| Label | Count |
|---|---|
| wrong_value | 19 |
| empty_result | 8 |
| wrong_number_of_values | 5 |
| no_sql_found | 3 |
| syntax_error | 2 |

These labels are automatic and rough. Open `failures_to_audit.csv`, read each failure and write your own label in the `your_label` column. That manual taxonomy is the most valuable part of this project.

Sanity-check flags raised on the voted answers: no_valid_query=6, type_mismatch=3

## Read this before you quote any number

- Method D answers fewer questions, so its accuracy is NOT comparable with A, B and C. Always quote accuracy together with coverage.
- With a small number of questions the confidence intervals are wide. Say so.
- Answers are compared as sets of values after simple normalisation (see `vtqa/scoring.py`).