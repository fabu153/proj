"""Onset cohort and point-in-time history sequences for gru_onset_v1 (torch-free, so CI can test them)."""
from __future__ import annotations

import numpy as np
import pandas as pd

TARGET = "label_onset"
YEARS = 3


def onset_cohort(df: pd.DataFrame) -> pd.DataFrame:
    """Canonical onset rows; asserts that no undeterminable or stressed year-t row slipped in."""
    sub = df[df[TARGET].notna()]
    assert sub["stress_t"].notna().all() and (sub["stress_t"] == 0).all(), "onset rows must be confirmed not stressed"
    assert sub["label_next_fy"].notna().all() and (sub[TARGET] == sub["label_next_fy"]).all()
    return sub


def history_index(rows: pd.DataFrame, all_feats: pd.DataFrame) -> list[list]:
    """For each row: indices into all_feats of the available years, oldest first, ending with year t."""
    allf = all_feats.assign(_fye=pd.to_datetime(all_feats["fiscal_year_end"]),
                            _asof=pd.to_datetime(all_feats["as_of_date"]))
    by_cik = {c: g.sort_values("_fye") for c, g in allf.groupby("cik")}
    out = []
    for _, row in rows.iterrows():
        g = by_cik[row["cik"]]
        fye, asof = pd.Timestamp(row["fiscal_year_end"]), pd.Timestamp(row["as_of_date"])
        cur = g[g["_fye"] == fye].index[0]
        steps = []
        for n in (2, 1):
            prev = g[(g["_fye"] < fye) & ((fye - g["_fye"]).dt.days.between(330 * n, 400 * n)) & (g["_asof"] <= asof)]
            if len(prev):
                steps.append((n, prev.index[-1]))
        out.append(steps + [(0, cur)])
    return out


def sequences(hist: list[list], Z: np.ndarray, zpos: dict) -> tuple[np.ndarray, np.ndarray]:
    """Padded (n, 3, F+1) array with the available years packed at the front, and the true lengths.
    The extra input is years-before-t / 2 (1.0 for t-2, 0.5 for t-1, 0 for t). Padding is never read by the GRU."""
    n, width = len(hist), Z.shape[1] + 1
    X = np.zeros((n, YEARS, width), dtype=np.float32)
    lengths = np.zeros(n, dtype=np.int64)
    for r, steps in enumerate(hist):
        for k, (back, idx) in enumerate(steps):
            X[r, k, :-1], X[r, k, -1] = Z[zpos[idx]], back / 2
        lengths[r] = len(steps)
    return X, lengths
