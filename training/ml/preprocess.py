"""Train-only preprocessing (Blueprint p.11 step 04; test M02).

fit() sees TRAINING rows only and learns: winsorization bounds (1st/99th pct), medians for
imputation, and mean/std for scaling. transform() applies the identical frozen parameters to
any split and appends one missingness indicator per feature, so the model can learn from
"undefined" (e.g. leverage with negative EBITDA) instead of a silently imputed value.
Parameters serialize to JSON so the API applies exactly what training used.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd


@dataclass
class Preprocessor:
    features: list[str]
    lower_q: float = 0.01
    upper_q: float = 0.99
    lo: dict[str, float] = field(default_factory=dict)
    hi: dict[str, float] = field(default_factory=dict)
    median: dict[str, float] = field(default_factory=dict)
    mean: dict[str, float] = field(default_factory=dict)
    std: dict[str, float] = field(default_factory=dict)
    fitted_on_rows: int = 0

    def fit(self, train: pd.DataFrame) -> "Preprocessor":
        for f in self.features:
            col = train[f].astype(float)
            lo, hi = col.quantile(self.lower_q), col.quantile(self.upper_q)
            lo = 0.0 if np.isnan(lo) else float(lo)
            hi = 0.0 if np.isnan(hi) else float(hi)
            clipped = col.clip(lo, hi)
            med = clipped.median()
            self.lo[f], self.hi[f] = lo, hi
            self.median[f] = 0.0 if np.isnan(med) else float(med)
            filled = clipped.fillna(self.median[f])
            self.mean[f] = float(filled.mean())
            sd = float(filled.std(ddof=0))
            self.std[f] = sd if sd > 1e-12 else 1.0
        self.fitted_on_rows = int(len(train))
        return self

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        if not self.fitted_on_rows:
            raise RuntimeError("Preprocessor not fitted")
        out = {}
        for f in self.features:
            col = df[f].astype(float)
            out[f] = ((col.clip(self.lo[f], self.hi[f]).fillna(self.median[f]) - self.mean[f]) / self.std[f])
        for f in self.features:
            out[f"{f}__missing"] = df[f].isna().astype(float)
        return pd.DataFrame(out, index=df.index)

    def output_columns(self) -> list[str]:
        return self.features + [f"{f}__missing" for f in self.features]

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=1)

    @classmethod
    def from_json(cls, s: str) -> "Preprocessor":
        return cls(**json.loads(s))
