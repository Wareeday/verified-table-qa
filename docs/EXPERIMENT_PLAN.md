# Experiment plan (fill this in and COMMIT it before your real run)

A dated commit of this file shows that you decided what to test *before* you saw the results.
Negative or mixed results are fine. Changing the plan after you have seen the numbers is not.
If you change anything later, add a note at the bottom saying what changed and why.

**Date written:** ____________  **Model(s):** ____________  **Questions (n):** ____________

## The question

When a language model writes SQL for a question about a table, does asking for several queries,
running them, and trusting only the answers they agree on make the answers more reliable?
And can the system tell which of its answers to trust?

## Settings I will NOT change after I start

| Setting | Value |
|---|---|
| Dataset | `wikitq`, random-split-1-dev, seed 7, tables up to 60 rows and 12 columns |
| Queries per question (K) | 3 (plain, plan, careful prompts) |
| Confidence threshold (tau) | 0.66 (at least 2 of 3 queries agree) |
| Temperature | 0 |
| Confidence intervals | 95% bootstrap, 2,000 resamples |
| Model(s) | |
| Number of questions | |

## Hypotheses

**H1 (voting).** Majority vote of 3 queries is more accurate than a single query on the same questions.
*Supported if* the paired difference (C minus B) is positive and its 95% CI excludes 0.

**H2 (confidence is informative).** Questions with high confidence are answered correctly more often than
questions with low confidence.
*Supported if* AUROC is above 0.5 with a 95% CI that excludes 0.5, and accuracy on answered questions is
above accuracy on refused questions.

**H3 (abstaining has a price).** Raising the confidence threshold raises accuracy on answered questions but
lowers coverage, and most gains come from refusing hard questions rather than answering more of them correctly.
*Supported if* the accuracy-vs-coverage curve rises as coverage falls, while coverage at tau = 0.66 is clearly below 100%.

**H4 (where it fails, optional).** Most wrong single queries fail because of *schema linking* (wrong column or
wrong filter value) and not because of SQL syntax.
*Supported if* in my manual audit of about 30 failures, schema-linking errors are the largest group.

## What I will report, whatever happens

- Accuracy with 95% CI for A (direct), B (one query), C (vote), and D (vote + abstain) **together with coverage**
- The paired differences C minus B and B minus A
- AUROC and the accuracy-vs-coverage table
- My manual error labels for about 30 failures, with counts
- All limitations in the README, including the filter on table size

## What would count as a negative result (and still be worth reporting)

- The CI for C minus B includes 0: voting did not help at this sample size.
- AUROC near 0.5: the agreement signal does not predict correctness for this model.
- Direct from the table beats SQL: for small tables, reading the table may be enough.

## Results log (fill in after the run)

| Run folder | Model | n | A direct | B one query | C vote | D accuracy / coverage | AUROC |
|---|---|---|---|---|---|---|---|
| | | | | | | | |

## Changes after seeing results (be honest)

-
