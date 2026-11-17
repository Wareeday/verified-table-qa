"""Turn predictions.jsonl into numbers, a plot, a markdown report and an error-audit sheet."""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

from .stats import auroc, bootstrap_ci


def load_records(run_dir) -> list:
    path = Path(run_dir) / "predictions.jsonl"
    recs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            recs.append(json.loads(line))
    return recs


def _pct(x) -> str:
    return "n/a" if x is None or x != x else f"{100 * x:.1f}%"


def _ci(lo, hi) -> str:
    return "n/a" if lo != lo or hi != hi else f"{100 * lo:.1f}% to {100 * hi:.1f}%"


def _sel_acc(conf, ok, tau):
    m = conf >= tau - 1e-9
    return float(ok[m].mean()) if m.any() else float("nan")


def _sel_cov(conf, tau):
    return float((conf >= tau - 1e-9).mean())


def compute_metrics(recs: list, tau: float, n_boot: int = 2000, seed: int = 0) -> dict:
    n = len(recs)
    conf = np.array([r["verdict"]["confidence"] for r in recs], dtype=float)
    single = np.array([r["single"]["correct"] for r in recs], dtype=float)
    vote = np.array([r["vote"]["correct"] for r in recs], dtype=float)
    has_direct = all(r.get("direct") for r in recs)
    direct = np.array([r["direct"]["correct"] for r in recs], dtype=float) if has_direct else None

    def acc(arr):
        return float(arr.mean()), *bootstrap_ci(np.mean, arr, n_boot=n_boot, seed=seed)

    m = {"n": n, "tau": tau}
    m["single"] = acc(single)
    m["vote"] = acc(vote)
    if has_direct:
        m["direct"] = acc(direct)
        m["diff_single_minus_direct"] = (float((single - direct).mean()),
                                         *bootstrap_ci(lambda a, b: np.mean(a - b), single, direct, n_boot=n_boot, seed=seed))
    m["diff_vote_minus_single"] = (float((vote - single).mean()),
                                   *bootstrap_ci(lambda a, b: np.mean(a - b), vote, single, n_boot=n_boot, seed=seed))
    m["selective_acc"] = (_sel_acc(conf, vote, tau),
                          *bootstrap_ci(lambda c, v: _sel_acc(c, v, tau), conf, vote, n_boot=n_boot, seed=seed))
    m["coverage"] = (_sel_cov(conf, tau),
                     *bootstrap_ci(lambda c: _sel_cov(c, tau), conf, n_boot=n_boot, seed=seed))
    rej = conf < tau - 1e-9
    m["rejected_acc"] = float(vote[rej].mean()) if rej.any() else float("nan")
    m["auroc"] = (auroc(conf, vote),
                  *bootstrap_ci(lambda c, v: auroc(c, v), conf, vote, n_boot=n_boot, seed=seed))
    curve = []
    for t in sorted(set(conf.tolist()), reverse=True):
        curve.append({"tau": t, "coverage": _sel_cov(conf, t), "accuracy": _sel_acc(conf, vote, t)})
    m["curve"] = curve
    m["difficulty"] = {}
    diffs = sorted({r["difficulty"] for r in recs if r.get("difficulty")})
    for d in diffs:
        idx = np.array([r.get("difficulty") == d for r in recs])
        m["difficulty"][d] = {
            "n": int(idx.sum()), "single": float(single[idx].mean()), "vote": float(vote[idx].mean()),
            "selective_acc": _sel_acc(conf[idx], vote[idx], tau), "coverage": _sel_cov(conf[idx], tau),
        }
    wrong = [r["single"]["label"] for r in recs if not r["single"]["correct"]]
    m["failure_labels"] = dict(Counter(wrong))
    m["flag_counts"] = dict(Counter(f for r in recs for f in r["verdict"]["flags"]))
    return m


def _plot(m: dict, out_png: Path, title: str):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6.4, 4.4))
    cov = [p["coverage"] for p in m["curve"]]
    acc = [p["accuracy"] for p in m["curve"]]
    ax.plot(cov, acc, "o-", color="#1F3864", label="vote + abstain")
    for p in m["curve"]:
        ax.annotate(f"conf>={p['tau']:.2f}", (p["coverage"], p["accuracy"]), textcoords="offset points",
                    xytext=(4, 5), fontsize=7)
    ax.axhline(m["single"][0], color="#C00000", ls="--", lw=1, label="one SQL query (all questions)")
    ax.axhline(m["vote"][0], color="#7F7F7F", ls=":", lw=1.2, label="majority vote (all questions)")
    if "direct" in m:
        ax.axhline(m["direct"][0], color="#2E7D32", ls="-.", lw=1, label="direct from table (all questions)")
    ax.set_xlabel("coverage (share of questions answered)")
    ax.set_ylabel("accuracy on answered questions")
    ax.set_xlim(0, 1.03)
    ax.set_ylim(0, 1.1)
    ax.set_title(title, fontsize=10)
    ax.legend(fontsize=7, loc="lower left")
    fig.tight_layout()
    fig.savefig(out_png, dpi=150)
    plt.close(fig)


def write_audit_csv(recs: list, path: Path):
    """The sheet for your manual error analysis: fill the 'your_label' column by hand."""
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "question", "gold_answer", "predicted_sql", "predicted_answer", "auto_label",
                    "gold_sql", "your_label", "your_notes"])
        for r in recs:
            if r["single"]["correct"]:
                continue
            first = r["candidates"][0]
            w.writerow([r["id"], r["question"], " | ".join(r["gold"]), first["sql"],
                        " | ".join(r["single"]["answer"]), r["single"]["label"], r.get("gold_sql") or "", "", ""])


def make_report(run_dir, tau: float = None, n_boot: int = 2000) -> Path:
    run_dir = Path(run_dir)
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8")) if (run_dir / "meta.json").exists() else {}
    recs = load_records(run_dir)
    if not recs:
        raise SystemExit("predictions.jsonl is empty - nothing to report")
    tau = tau if tau is not None else meta.get("tau", 0.66)
    m = compute_metrics(recs, tau, n_boot=n_boot)
    is_mock = meta.get("backend") == "mock"
    k = meta.get("k", "?")
    _plot(m, run_dir / "coverage_curve.png",
          f"{meta.get('dataset', '')} - {meta.get('model', '')} (n={m['n']})" + ("  [MOCK]" if is_mock else ""))
    write_audit_csv(recs, run_dir / "failures_to_audit.csv")

    L = []
    L.append("# Verified Table QA - run report\n")
    if is_mock:
        L.append("> **MOCK RUN.** These numbers come from a fake model that was built to test the code. "
                 "They say nothing about real language models. Do not quote them anywhere.\n")
    L.append(f"- Dataset: `{meta.get('dataset', '?')}`  |  Model: `{meta.get('model', '?')}`  |  Questions: **{m['n']}**")
    L.append(f"- Queries per question (K): **{k}**  |  Confidence threshold: **{tau}**  |  Seed: {meta.get('seed', '?')}\n")
    L.append("## Headline numbers (95% bootstrap confidence intervals)\n")
    L.append("| Method | Accuracy | 95% CI |")
    L.append("|---|---|---|")
    if "direct" in m:
        L.append(f"| A. Direct from the table (no SQL) | {_pct(m['direct'][0])} | {_ci(*m['direct'][1:])} |")
    L.append(f"| B. SQL, one query | {_pct(m['single'][0])} | {_ci(*m['single'][1:])} |")
    L.append(f"| C. SQL, majority vote of K queries (answers everything) | {_pct(m['vote'][0])} | {_ci(*m['vote'][1:])} |")
    L.append(f"| D. Vote + abstain: accuracy on the questions it answered | {_pct(m['selective_acc'][0])} | {_ci(*m['selective_acc'][1:])} |")
    L.append(f"| D. Coverage (share of questions answered) | {_pct(m['coverage'][0])} | {_ci(*m['coverage'][1:])} |\n")
    L.append("Paired differences (same questions, so this is the fair comparison):\n")
    d = m["diff_vote_minus_single"]
    L.append(f"- Voting vs one query (C minus B): **{100 * d[0]:+.1f} points**, 95% CI {100 * d[1]:+.1f} to {100 * d[2]:+.1f}")
    if "diff_single_minus_direct" in m:
        d = m["diff_single_minus_direct"]
        L.append(f"- SQL vs direct (B minus A): **{100 * d[0]:+.1f} points**, 95% CI {100 * d[1]:+.1f} to {100 * d[2]:+.1f}")
    L.append("\nIf a confidence interval for a difference includes 0, you cannot say the two methods differ "
             "at this sample size.\n")
    L.append("## Does the confidence score separate right from wrong?\n")
    a = m["auroc"]
    L.append(f"- AUROC of confidence vs correctness: **{a[0]:.2f}** (95% CI {a[1]:.2f} to {a[2]:.2f}). "
             "0.50 means the score is useless; 1.00 means perfect.")
    L.append(f"- Accuracy on answered questions: {_pct(m['selective_acc'][0])}. "
             f"Accuracy on the questions it refused: {_pct(m['rejected_acc'])}.\n")
    L.append("## Accuracy vs coverage (every possible threshold)\n")
    L.append("| confidence >= | coverage | accuracy on answered |")
    L.append("|---|---|---|")
    for p in m["curve"]:
        L.append(f"| {p['tau']:.2f} | {_pct(p['coverage'])} | {_pct(p['accuracy'])} |")
    L.append("\n![coverage curve](coverage_curve.png)\n")
    if m["difficulty"]:
        L.append("## By difficulty\n")
        L.append("| Difficulty | n | One query | Vote (all) | Vote + abstain accuracy | Coverage |")
        L.append("|---|---|---|---|---|---|")
        for dname in ("easy", "medium", "hard"):
            if dname in m["difficulty"]:
                x = m["difficulty"][dname]
                L.append(f"| {dname} | {x['n']} | {_pct(x['single'])} | {_pct(x['vote'])} | "
                         f"{_pct(x['selective_acc'])} | {_pct(x['coverage'])} |")
        L.append("")
    L.append("## Why the single query was wrong (automatic first-pass labels)\n")
    if m["failure_labels"]:
        L.append("| Label | Count |")
        L.append("|---|---|")
        for lab, c in sorted(m["failure_labels"].items(), key=lambda kv: -kv[1]):
            L.append(f"| {lab} | {c} |")
        L.append("\nThese labels are automatic and rough. Open `failures_to_audit.csv`, read each failure "
                 "and write your own label in the `your_label` column. That manual taxonomy is the "
                 "most valuable part of this project.\n")
    else:
        L.append("No failures to label.\n")
    if m["flag_counts"]:
        L.append("Sanity-check flags raised on the voted answers: " +
                 ", ".join(f"{k}={v}" for k, v in sorted(m["flag_counts"].items())) + "\n")
    L.append("## Read this before you quote any number\n")
    L.append("- Method D answers fewer questions, so its accuracy is NOT comparable with A, B and C. "
             "Always quote accuracy together with coverage.")
    L.append("- With a small number of questions the confidence intervals are wide. Say so.")
    L.append("- Answers are compared as sets of values after simple normalisation (see `vtqa/scoring.py`).")
    out = run_dir / "report.md"
    out.write_text("\n".join(L), encoding="utf-8")
    (run_dir / "summary.json").write_text(json.dumps(m, indent=2, default=float), encoding="utf-8")
    return out


if __name__ == "__main__":
    path = make_report(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else None)
    print("wrote", path)
