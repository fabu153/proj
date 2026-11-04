"""Week 2 deliverable: dataset coverage report + label audit (markdown)."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

SIC_DIVISIONS = [(100, 999, "Agriculture"), (1000, 1499, "Mining & energy"), (1500, 1799, "Construction"),
                 (2000, 3999, "Manufacturing"), (4000, 4899, "Transport & communications"),
                 (4900, 4999, "Utilities"), (5000, 5199, "Wholesale"), (5200, 5999, "Retail"),
                 (7000, 8999, "Services"), (9000, 9999, "Other / public admin")]


def sic_division(sic) -> str:
    try:
        s = int(sic)
    except (TypeError, ValueError):
        return "Unknown"
    return next((name for lo, hi, name in SIC_DIVISIONS if lo <= s <= hi), "Unknown")


def _table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(map(str, cols)) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(f"{x:.3f}" if isinstance(x, float) else str(x) for x in r) + " |")
    return "\n".join(lines)


def _prev(g: pd.DataFrame, col: str) -> pd.Series:
    lab = g[g[col].notna()]
    return pd.Series({"labelled": len(lab), "positives": int(lab[col].sum()),
                      "prevalence": lab[col].mean() if len(lab) else float("nan")})


def write_report(df: pd.DataFrame, universe: list[dict], failures: list[dict], path: str) -> None:
    df = df.copy()
    df["fy"] = df["fiscal_year_end"].str[:4].astype(int)
    df["division"] = df["sic"].map(sic_division)
    lab = df[df["label_next_fy"].notna()]
    out = [f"# CreditLens dataset coverage report & label audit",
           f"_Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC from SEC XBRL companyfacts. "
           f"Label version: {df['label_version'].iloc[0]}._", "",
           "## Universe and panel",
           f"- Companies in universe: **{len(universe)}**; with ≥1 annual row: **{df['cik'].nunique()}**; "
           f"fetch/parse failures: **{len(failures)}**",
           f"- Company-years: **{len(df)}** (fiscal years {df['fy'].min()}–{df['fy'].max()})",
           f"- Passing hard checks (scorable): **{df['scorable'].mean():.1%}**",
           f"- Mean critical-field coverage: **{df['critical_coverage'].mean():.1%}**; "
           f"rows with all 7 critical fields: **{(df['critical_coverage'] == 1).mean():.1%}**",
           f"- Rows with a determinable next-year label: **{len(lab)}** ({len(lab)/len(df):.1%})", "",
           "### Why rows have no label", _table(df["label_reason"].fillna("labelled").replace("", "labelled")
                                                .value_counts().rename_axis("reason").reset_index()), "",
           "### Field availability (share of company-years with a value)",
           _table(pd.DataFrame({"field": [c[2:] for c in df.columns if c.startswith("v_")],
                                "available": [df[c].notna().mean() for c in df.columns if c.startswith("v_")]})
                  .sort_values("available")), "",
           "## Label audit — next-fiscal-year stress (2 of 3)",
           f"- Overall prevalence: **{lab['label_next_fy'].mean():.2%}** "
           f"({int(lab['label_next_fy'].sum())} positives / {len(lab)})",
           f"- Onset prevalence (not stressed in t): **{lab['label_onset'].dropna().mean():.2%}** "
           f"({int(lab['label_onset'].dropna().sum())} positives / {lab['label_onset'].notna().sum()})",
           f"- Persistence: P(stress t+1 | stress t) = "
           f"**{lab.loc[lab['stress_t'] == 1, 'label_next_fy'].mean():.1%}**; "
           f"P(stress t+1 | not stress t) = **{lab.loc[lab['stress_t'] == 0, 'label_next_fy'].mean():.1%}**", "",
           "### Which conditions fire in year t (all scorable rows)",
           _table(pd.DataFrame({"condition": ["EBIT cover < 1.5x", "Debt/EBITDA > 5x or debt w/ EBITDA ≤ 0",
                                              "CFO < 0"],
                                "share_true": [df["cond_cov_t"].eq(True).mean(), df["cond_lev_t"].eq(True).mean(),
                                               df["cond_cfo_t"].eq(True).mean()],
                                "share_unknown": [df["cond_cov_t"].isna().mean(), df["cond_lev_t"].isna().mean(),
                                                  df["cond_cfo_t"].isna().mean()]})), "",
           "### Prevalence by fiscal year (t)",
           _table(lab.groupby("fy").apply(_prev, "label_next_fy", include_groups=False).reset_index()), "",
           "### Prevalence by size quintile (1 = smallest)",
           _table(lab.groupby("size_quintile").apply(_prev, "label_next_fy", include_groups=False).reset_index()), "",
           "### Prevalence by sector (SIC division)",
           _table(lab.groupby("division").apply(_prev, "label_next_fy", include_groups=False).reset_index()), "",
           "## Known limitations",
           "- Proxy for accounting stress, not default; thresholds are declared assumptions (configs/assumptions.yaml).",
           "- EBITDA = operating income + D&A (unadjusted); D&A tag coverage limits EBITDA availability.",
           "- Interest-expense tagging varies (gross/net, capitalized); missing interest leaves coverage unknown.",
           "- Companies absent from all four assets snapshots (2011/15/19/22) are not in the universe.",
           "- XBRL begins ~2009-2011 depending on filer size; earliest years are thinner.", ""]
    if failures:
        out += ["## Failures (first 25)", _table(pd.DataFrame(failures).head(25)), ""]
    with open(path, "w") as fh:
        fh.write("\n".join(out))
