# Verified Table QA

**Can a language model learn to say "I'm not sure" about its own SQL?**

This is a small research project about *trusting* what a language model tells you. A model reads a question about a table, writes SQL, and we **run** that SQL. Then we ask: how do we know the answer is right? My answer is simple. We ask the model for the query three different ways, run all three, and only trust the answer when the attempts agree. When they don't, the system says *"I don't know"* instead of guessing.

The project measures whether this actually helps, and how much, with proper confidence intervals instead of a single lucky number.

I started it because of one question that I could not put down: *if an AI system can run a hundred experiments while I sleep, how do I know its results are real?* Tables and SQL are a good place to study that question, because a SQL query can be executed and checked by a computer.

> **Honest status.** The code is complete and tested (see "Tests" below), but I have not put any results in this repository yet. Run it, then add your own numbers. Never copy numbers from a "mock" run. The mock model is fake and exists only to test the code.

---

## How it works

```
 question + table schema
          │
          ├─► ask the model for 3 SQL queries (3 different prompts)
          ├─► run every query on a read-only SQLite copy of the table
          ├─► compare the answers - the majority answer wins
          └─► confidence = (queries that agree) / 3,  halved if a sanity check fails
                    │
        confidence >= threshold ?  ──► yes: give the answer
                                   └─► no : abstain ("I don't know")
```

**The three prompts** (`vtqa/prompts.py`): a plain one, one that asks the model to plan first, and one with a short list of SQL rules.

**The sanity checks** (`vtqa/verify.py`) need no extra model call:

| Check | What it catches |
|---|---|
| `type_mismatch` | a "how many..." question must return exactly one number |
| `ungrounded` | a text answer must appear in a table cell, so it was not made up |
| empty / null result | a query that returns nothing cannot vote |

A query that crashes still counts in the denominator. That is on purpose: a model that often writes broken SQL should *lose* confidence.

### What gets compared

| | Method | Answers every question? |
|---|---|---|
| A | **Direct**: show the model the whole table, ask for the answer | yes |
| B | **SQL, one query**: schema only, one query, run it | yes |
| C | **SQL + majority vote** of 3 queries | yes |
| D | **SQL + vote + abstain** (this project's main idea) | only when confident |

Comparing B with C tells you if *voting* helps. Looking at D tells you if *abstaining* helps. They are separate questions, and a careful report keeps them separate.

---

## Quick start (2 minutes, no model needed)

You need Python 3.9 or newer.

```bash
git clone <your-repo-url>
cd verified-table-qa

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python tests/test_all.py           # should end with: ALL TESTS PASSED
python run.py --dataset mini --backend mock --n 30 --out results/demo_mock
```

Open `results/demo_mock/report.md`. You will see a big **MOCK RUN** warning. That is correct: the mock model is a fake that breaks the right SQL on purpose. It proves the code works. It says nothing about real models.

---

## Run it with a real model (free)

You do not need to pay anything. Pick one option.

### Option 1: Ollama on your own computer (free, no limits)

1. Install Ollama from https://ollama.com
2. Download a model. This one is good at SQL and needs about 5 GB:
   ```bash
   ollama pull qwen2.5-coder:7b
   ```
   If your computer has less than 8 GB of RAM, try a smaller one, for example `qwen2.5-coder:3b`.
3. Run (Ollama must be running in the background):
   ```bash
   python run.py --dataset mini --n 60 --preset ollama --model qwen2.5-coder:7b --out results/mini_qwen7b
   ```

A note about memory: the "direct" baseline sends a whole table to the model. If your Ollama version uses a small context window, that baseline can look unfairly bad. Raise the context length (check the Ollama docs for your version) or add `--skip-direct`.

### Option 2: a free API tier (Groq, Gemini, OpenRouter)

1. Make a free account with the provider and create an API key.
2. Put the key in an environment variable. **Never put a key inside the code or on GitHub.**
   ```bash
   export GROQ_API_KEY="paste-your-key"          # Mac / Linux
   $env:GROQ_API_KEY="paste-your-key"            # Windows PowerShell
   ```
3. Run it. Use a model name from your provider's model list (names change over time) and be gentle with the rate limit:
   ```bash
   python run.py --dataset mini --n 60 --preset groq --model <model-name> --sleep 2 --out results/mini_groq
   ```

Presets: `ollama`, `groq`, `gemini`, `openrouter`. They set the web address and the name of the key variable (`GROQ_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`). Free limits change, so check the provider's page. Any other service that speaks the "OpenAI chat completions" format works too, with `--base-url`.

On Google Colab, use Option 2.

### What a run costs

For `n` questions the code makes about `n x 4` model calls (3 SQL queries + 1 direct answer). Every reply is saved in `llm_cache.jsonl`, so if a run stops, start the same command again and it continues where it stopped, without paying twice.

---

## Suggested order for your first real results

1. **Sanity check on the synthetic data** (`--dataset mini --n 60`). A decent model should do well here. If it does not, something is wrong with your setup, not with science.
2. **Real data** (`--dataset wikitq --n 100`). WikiTableQuestions has real Wikipedia tables and human-written questions, so it is much harder. This is the run to report.
3. If you have time, a **second, different model**. Comparing a small and a larger model is more interesting than one number.

Before you press enter on step 2, open `docs/EXPERIMENT_PLAN.md`, fill it in, and commit it. Writing your hypotheses first keeps you honest.

The real-data command:

```bash
python run.py --dataset wikitq --n 100 --preset ollama --model qwen2.5-coder:7b --out results/wikitq_qwen7b
```

The first run downloads the questions and tables from the public WikiTableQuestions GitHub page (nothing is stored in this repo). I keep only tables with at most 60 rows and 12 columns, so the direct baseline can see the whole table. Change this with `--max-table-rows`.

---

## Reading your report

Every run writes into its `--out` folder:

| File | What it is |
|---|---|
| `report.md` | the readable summary |
| `coverage_curve.png` | accuracy against coverage |
| `predictions.jsonl` | every question, every query, every answer (the raw evidence) |
| `failures_to_audit.csv` | the wrong answers, ready for you to label by hand |
| `summary.json` | all numbers, for your own plots |
| `meta.json` | model, settings, date |

In the report:

- **Accuracy and 95% CI.** The interval comes from bootstrapping the questions. With 100 questions it is wide. That is normal. Quote it.
- **Paired differences.** "Voting vs one query" is computed on the *same* questions. If its interval includes 0, you cannot claim a difference.
- **Coverage.** The share of questions the system actually answered. **Always quote accuracy together with coverage.** Method D looks great if it only answers the easy ones, which is exactly why you report both.
- **AUROC.** If you pick one right answer and one wrong answer at random, how often does the right one have the higher confidence? 0.50 = the score is useless, 1.00 = perfect.
- **Why queries failed.** First-pass labels made by a few simple rules.

### The manual error audit (do this, it is the best part)

Open `failures_to_audit.csv`. For about 30 wrong answers, read the question, the gold answer and the model's SQL, then write *why* it failed in the `your_label` column. Typical labels: wrong column, wrong filter value, wrong aggregation, misread the question, ambiguous question, bad gold answer. Then count them. A hand-made list of failure types, from real examples, is worth more than any single accuracy number.

---

## All options

| Option | Default | Meaning |
|---|---|---|
| `--dataset` | `mini` | `mini` (synthetic, offline) or `wikitq` (real) |
| `--n` | 60 | number of questions |
| `--seed` | 7 | which questions are picked |
| `--backend` | `openai` | `openai` = any compatible server, `mock` = fake model for testing |
| `--preset` | none | `ollama`, `groq`, `gemini`, `openrouter` |
| `--base-url`, `--model`, `--api-key-env` | none | for any other server |
| `--k` | 3 | queries per question (more than 3 adds repeats at temperature 0.7) |
| `--tau` | 0.66 | answer only if confidence is at least this; 0.66 means "2 of 3 agree". **Choose it before you look at results.** |
| `--no-samples` | off | show the model the schema only, without example rows |
| `--skip-direct` | off | skip baseline A to save calls |
| `--max-table-rows` | 60 | wikitq: skip longer tables |
| `--sleep` | 0 | seconds to wait after each call |
| `--out` | `results/run1` | output folder |

To rebuild a report with a different threshold: `python -m vtqa.report results/my_run 0.99`

---

## What is where

```
run.py                  command-line entry point
vtqa/
  prompts.py            every prompt (change them here)
  llm.py                model client, disk cache, and the fake mock model
  db.py                 SQLite loading, schema text, safe read-only execution
  methods.py            the direct baseline and the SQL queries
  verify.py             voting, sanity checks, confidence
  scoring.py            how answers are normalised and compared
  taxonomy.py           automatic first-pass failure labels
  stats.py              bootstrap confidence intervals, AUROC
  report.py             report, plot, audit sheet
  data_mini.py          synthetic company database + questions
  data_wikitq.py        WikiTableQuestions loader
tests/test_all.py       tests (no model, no internet needed)
docs/EXPERIMENT_PLAN.md fill in and commit before your real run
```

---

## Tests

`python tests/test_all.py` checks, among other things, that:

- SQL safety works: only `SELECT` runs, writes are blocked, and runaway queries are stopped after 3 seconds
- the synthetic questions are reproducible and their gold SQL gives the gold answer
- the verifier votes, flags and breaks ties as documented
- a perfect model gets 100% with full coverage, so the verifier does not raise false alarms
- the HTTP client works against a local fake server, including retry after a rate-limit error
- an interrupted run resumes without calling the model again

`VTQA_ONLINE=1 python tests/test_all.py` also checks the real WikiTableQuestions download.

What the tests **cannot** tell you: how real models behave. That is what your run is for.

---

## Limits you should know about (and write down)

- **Answers are compared as sets** of normalised values. Order and duplicates are ignored, numbers are rounded to 2 decimals, and "which of these, in order" questions are not scored strictly.
- **WikiTableQuestions is filtered** to small tables, and it is public, so a model may have seen it during training.
- **The three prompts are not independent samples.** Their agreement is a useful signal, but it is weaker than three independent draws. Models can also be consistently wrong.
- **Column names are cleaned** (`"Avg. Attendance"` becomes `avg_attendance`) so SQLite accepts them. The original headers are shown to the model as a note.
- **A small number of questions means wide intervals.** Do not call a result a "discovery" on 100 questions.
- **The prompts were not tuned.** I wrote them once. A model-specific prompt would probably score higher.
- **The mini dataset is synthetic.** It is a sanity check, not a benchmark.

---

## Troubleshooting

| Problem | Try this |
|---|---|
| `Could not talk to the model` | Is Ollama running? Is the model name exactly right (`ollama list`)? Is the key variable set in *this* terminal? |
| Every query is empty or broken | The model may be too small. Try a bigger one, or look at a few rows of `predictions.jsonl`. |
| `HTTP 429` or very slow | You hit a free-tier limit. Add `--sleep 3` and run again; finished questions are skipped. |
| The direct baseline looks terrible | Probably a small context window. See the Ollama note above or use `--skip-direct`. |
| wikitq download fails | Check your internet. Downloaded files are cached in `data_cache/`. |
| Want a clean start | Delete the `--out` folder. |

---

## Ideas to extend it

- Add the **Spider** benchmark (multi-table databases). Only `data_*.py` needs a new loader.
- Replace the confidence rule with a **small learned classifier** and compare it with simple voting.
- Add a second, independent way of computing the answer (for example pandas) as a stronger verifier.
- Try a harder setting: tables with dates and time arithmetic, where small models break often.

---

## References and credits

- WikiTableQuestions: Pasupat and Liang, *Compositional Semantic Parsing on Semi-Structured Tables*, ACL 2015. https://github.com/ppasupat/WikiTableQuestions . Please read the dataset page for its terms of use.
- Voting over several answers is the idea of self-consistency (Wang et al., 2023), and ranking SQL or code by what it *executes to* has been studied before (for example Shi et al., 2022). Choosing to abstain follows the selective-prediction literature (El-Yaniv and Wiener, 2010; Geifman and El-Yaniv, 2017). **This project is not a new method.** It is a small, careful evaluation of a known idea.
- Related research I was inspired by: Kulkarni et al., *LLM-Symbolic Integration for Robust Temporal Tabular Reasoning* (Findings of ACL 2025), where a model writes SQL over a table.

This project was built with the help of an AI coding assistant (Claude). Read the code and run the tests before you trust it.

## License

MIT
