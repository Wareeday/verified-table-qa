"""Tiny statistics helpers (no scipy needed)."""
from __future__ import annotations

import numpy as np


def bootstrap_ci(fn, *arrays, n_boot: int = 2000, seed: int = 0, alpha: float = 0.05):
    """95% bootstrap confidence interval of fn(*arrays), resampling questions with replacement."""
    arrays = [np.asarray(a, dtype=float) for a in arrays]
    n = len(arrays[0])
    if n == 0:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        v = fn(*[a[idx] for a in arrays])
        if v == v:  # skip NaN
            vals.append(v)
    if not vals:
        return float("nan"), float("nan")
    return float(np.percentile(vals, 100 * alpha / 2)), float(np.percentile(vals, 100 * (1 - alpha / 2)))


def _rankdata(a: np.ndarray) -> np.ndarray:
    order = np.argsort(a, kind="mergesort")
    sorted_a = a[order]
    ranks = np.empty(len(a), dtype=float)
    i = 0
    while i < len(a):
        j = i
        while j + 1 < len(a) and sorted_a[j + 1] == sorted_a[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def auroc(scores, labels) -> float:
    """Chance that a random correct answer has a higher confidence than a random wrong one.
    0.5 = confidence is useless, 1.0 = perfect."""
    scores = np.asarray(scores, dtype=float)
    labels = np.asarray(labels, dtype=float)
    pos = labels == 1
    n_pos, n_neg = int(pos.sum()), int((~pos).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    ranks = _rankdata(scores)
    return float((ranks[pos].sum() - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))
