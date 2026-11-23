"""Chronological, purged train/validation/test split (Blueprint p.07, p.11).

Rows are assigned by `as_of_date` (when year-t features became public):
    train : as_of_date <  val_start
    val   : val_start  <= as_of_date < test_start
    test  : test_start <= as_of_date < test_end
Purge: a row is dropped from its split if its LABEL became public on/after the next split's
start — otherwise training would contain outcomes that were not yet observable when the
later window's predictions are made. The test window is frozen in the config before any
model is fitted.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class SplitSpec:
    val_start: str
    test_start: str
    test_end: str


def assign_splits(df: pd.DataFrame, spec: SplitSpec) -> pd.Series:
    asof = pd.to_datetime(df["as_of_date"])
    lab = pd.to_datetime(df["label_available_date"])
    v0, t0, t1 = map(pd.Timestamp, (spec.val_start, spec.test_start, spec.test_end))
    split = pd.Series("excluded", index=df.index)
    split[(asof < v0) & (lab < v0)] = "train"
    split[(asof >= v0) & (asof < t0) & (lab < t0)] = "val"
    split[(asof >= t0) & (asof < t1) & lab.notna()] = "test"
    return split


def audit_splits(df: pd.DataFrame, split: pd.Series) -> dict:
    """Facts the report prints and the tests assert (M01/M02)."""
    out = {}
    for s in ("train", "val", "test"):
        d = df[split == s]
        out[s] = {"rows": int(len(d)), "companies": int(d["cik"].nunique()),
                  "positives": int(d["label_next_fy"].sum()), "prevalence": float(d["label_next_fy"].mean()),
                  "as_of_min": str(d["as_of_date"].min()), "as_of_max": str(d["as_of_date"].max()),
                  "label_available_max": str(d["label_available_date"].max())}
    out["excluded_rows"] = int((split == "excluded").sum())
    return out


def walk_forward_masks(df: pd.DataFrame, year: int, val_years: int) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Expanding-window fold for test year `year` (walk_forward_v1).

    train: filed before the validation window AND label public before it;
    val:   filed in [year - val_years, year) AND label public before the test year;
    test:  filed in `year`, with an observed label (its publication date may be later: it is only scored).
    """
    asof, lab = pd.to_datetime(df["as_of_date"]), pd.to_datetime(df["label_available_date"])
    v0, t0, t1 = (pd.Timestamp(f"{year - val_years}-01-01"), pd.Timestamp(f"{year}-01-01"),
                  pd.Timestamp(f"{year + 1}-01-01"))
    train = (asof < v0) & (lab < v0)
    val = (asof >= v0) & (asof < t0) & (lab < t0)
    test = (asof >= t0) & (asof < t1) & lab.notna()
    return train, val, test
