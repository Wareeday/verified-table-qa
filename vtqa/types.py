"""The one data structure shared by all datasets."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Example:
    id: str
    question: str
    tables: dict                    # table name -> DataFrame (clean column names, used to build SQLite)
    gold_answer: list               # list of normalised strings
    table_key: str                  # examples with the same key share one SQLite database
    gold_sql: Optional[str] = None  # only the synthetic "mini" dataset has this
    difficulty: Optional[str] = None
    notes: str = ""                 # extra text shown to the model (e.g. original column headers)
    display_tables: Optional[dict] = None  # what the "direct" baseline sees (original headers)
