"""Generate docs/data_dictionary.md from the code registries (single source of truth).

    python -m training.pipeline.data_dictionary
"""
from pathlib import Path

from backend.app.documents.xbrl import HELPER_FIELDS, TAG_REGISTRY
from backend.app.labels import stress_label as sl
from backend.app.features.feature_set import FEATURE_DICTIONARY, FEATURE_VERSION


def main(out: str = "docs/data_dictionary.md") -> None:
    L = ["# CreditLens data dictionary", "",
         "Generated from code (`xbrl.TAG_REGISTRY`, `feature_set.FEATURE_DICTIONARY`, `stress_label`). "
         "Edit the code, then regenerate — never this file.", "",
         "## Canonical company-year facts (SEC XBRL, us-gaap, USD)", "",
         "| field | period | XBRL tags in priority order | role |", "|---|---|---|---|"]
    for k, (ptype, tags) in TAG_REGISTRY.items():
        role = "derivation input only" if k in HELPER_FIELDS else "engine input"
        L.append(f"| `{k}` | {ptype} | {', '.join(f'`{t}`' for t in tags)} | {role} |")
    L += ["", "Annual = 10-K/10-K/A/10-KT, duration 350–380 days. Original vintage by default; restatements kept. "
          "Derivation rules R1–R4 are documented in `backend/app/documents/xbrl.py::derive`.", "",
          f"## Model features (`{FEATURE_VERSION}`)", "", "| # | feature | definition | unit |", "|---|---|---|---|"]
    for i, (k, (desc, unit)) in enumerate(FEATURE_DICTIONARY.items(), 1):
        L.append(f"| {i} | `{k}` | {desc} | {unit} |")
    L += ["", "Each feature also gets a `<feature>__missing` indicator after train-only median imputation.", "",
          f"## Label (`{sl.LABEL_VERSION}`)", "",
          f"`label_next_fy` = 1 if at least {sl.MIN_CONDITIONS} of 3 hold in fiscal year t+1: "
          f"EBIT/interest < {sl.EBIT_COVER_MAX}x; gross debt/EBITDA > {sl.LEVERAGE_MAX}x (or debt with EBITDA ≤ 0); "
          f"CFO < {sl.CFO_MIN:g}. Undeterminable → missing (never 0). "
          "`label_onset` = same outcome restricted to firms not stressed in year t.", "",
          "## Panel columns (`training/data/panel_v1.csv`)", "",
          "| column | meaning |", "|---|---|",
          "| `as_of_date` | latest filing date of year-t facts — earliest moment a prediction can be made |",
          "| `label_available_date` | filing date of year t+1 facts — when the outcome became public |",
          "| `v_*` | canonical fact, USD millions | ",
          "| `m_*` | engine metric (`finance/metrics.py`) |",
          "| `stress_t`, `cond_*_t` | label rule applied to year t (feature-safe) |",
          "| `critical_coverage` | share of 7 critical facts present |", ""]
    Path(out).parent.mkdir(exist_ok=True)
    Path(out).write_text("\n".join(L))
    print("wrote", out)


if __name__ == "__main__":
    main()
