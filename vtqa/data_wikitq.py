"""WikiTableQuestions (Pasupat & Liang, 2015): real questions about real Wikipedia tables.

Nothing is stored in this repository. The question file and each table are downloaded from the
dataset's public GitHub page the first time you run, and cached in data_cache/.
Please read the dataset's own page for its terms: https://github.com/ppasupat/WikiTableQuestions
"""
from __future__ import annotations

import io
import random
import time
from pathlib import Path

import pandas as pd
import requests

from .db import sanitize_columns
from .scoring import normalize
from .types import Example

RAW = "https://raw.githubusercontent.com/ppasupat/WikiTableQuestions/master/"


def _download(path: str, cache_dir: Path) -> bytes:
    local = cache_dir / path.replace("/", "__")
    if local.exists():
        return local.read_bytes()
    last = ""
    for attempt in range(4):
        try:
            r = requests.get(RAW + path, timeout=60, headers={"User-Agent": "verified-table-qa"})
            if r.status_code == 200:
                cache_dir.mkdir(parents=True, exist_ok=True)
                local.write_bytes(r.content)
                return r.content
            last = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            last = str(e)
        time.sleep(2 ** attempt)
    raise RuntimeError(f"could not download {path}: {last}")


def _unescape(value: str) -> str:
    return value.replace("\\p", "|").replace("\\n", "\n").replace("\\\\", "\\")


def _coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    """Columns where every non-empty cell looks like a number become real numbers."""
    for col in df.columns:
        s = df[col].astype(str).str.strip()
        nonempty = s[s != ""]
        cleaned = nonempty.str.replace(",", "", regex=False)
        if len(nonempty) > 0 and cleaned.str.fullmatch(r"[-+]?\d+(\.\d+)?").all():
            df[col] = pd.to_numeric(s.str.replace(",", "", regex=False), errors="coerce")
    return df


def load_wikitq(n: int = 100, seed: int = 7, cache_dir: str = "data_cache/wikitq",
                split: str = "random-split-1-dev", max_rows: int = 60, max_cols: int = 12) -> list:
    cache = Path(cache_dir)
    tsv = _download(f"data/{split}.tsv", cache).decode("utf-8")
    rows = []
    for line in tsv.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) >= 4:
            rows.append((parts[0], parts[1], parts[2], parts[3]))
    rng = random.Random(seed)
    rng.shuffle(rows)
    examples, tried = [], 0
    for qid, question, csv_path, target in rows:
        if len(examples) >= n:
            break
        tried += 1
        if tried > n * 6 + 50:
            break
        try:
            raw = pd.read_csv(io.BytesIO(_download(csv_path, cache)), dtype=str, keep_default_na=False)
        except Exception:
            continue  # a few tables are malformed; skip them
        if len(raw) == 0 or len(raw) > max_rows or raw.shape[1] > max_cols:
            continue
        clean = raw.copy()
        clean.columns = sanitize_columns(raw.columns)
        clean = _coerce_numeric(clean)
        notes = "Original column headers: " + "; ".join(f"{c} = {o}" for c, o in zip(clean.columns, raw.columns))
        gold = [normalize(_unescape(v)) for v in target.split("|")]
        examples.append(Example(
            id=qid, question=question.strip(), tables={"t": clean}, gold_answer=gold,
            table_key=csv_path, notes=notes, display_tables={"t": raw},
        ))
    if not examples:
        raise RuntimeError("no WikiTableQuestions examples could be loaded (check your internet connection)")
    return examples
