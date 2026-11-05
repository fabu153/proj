"""Run the suite and write docs/test_matrix.md: every Blueprint p.22 test ID -> the tests that prove it.

    python scripts/test_matrix.py                    # unit + integration
    E2E_BASE_URL=http://localhost:3000 python scripts/test_matrix.py   # also browser tests
"""
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

MATRIX = [
    ("F01", "EBITDA / debt / coverage math", "Matches golden fixture", ["test_f01_", "test_golden_post_loan", "test_status_quo"]),
    ("F02", "Negative EBITDA / zero interest", "No misleading ratios or crash", ["test_f02_", "test_no_metric_ever_returns_nan"]),
    ("F03", "Refinancing versus capex use", "Correct net-debt effects", ["test_f03_", "test_engine_matches_spreadsheet"]),
    ("F04", "EUR loan against USD statements", "Explicit FX or blocked", ["test_f04_", "test_scenario_eur_facility"]),
    ("D01", "Annual vs quarterly classification", "No quarter as annual", ["test_d01_"]),
    ("D02", "Units and sign conventions", "Scaling detected", ["test_d02_", "test_prior_year_column", "test_capex_sign"]),
    ("D03", "PDF extraction uncertainty", "Low confidence requires review", ["test_d03_", "test_gate_blocks", "test_cross_check_flags", "test_full_upload_to_memo_flow"]),
    ("M01", "No future labels in model input", "As-of audit passes", ["test_m01_", "test_features_never_use_next_year", "test_panel_rows_are_point_in_time", "test_no_train_label_is_public"]),
    ("M02", "Train-only preprocessing", "Fold pipelines tested", ["test_preprocessor_fits_on_train_only", "test_purge_drops"]),
    ("M03", "Probability calibration", "Metrics + plot reported", ["test_probabilities_are_valid", "test_numpy_forward_matches_pytorch"]),
    ("M04", "Unknown / poor-coverage company", "Output withheld with reason", ["test_m04_"]),
    ("S01", "EBITDA -20%, rate +200 bp", "Expected outputs reproduced", ["test_s01_", "test_engine_matches_spreadsheet"]),
    ("G01", "Narrative numeric claims", "All reconcile to package", ["test_g01_", "test_rendered_numbers_equal", "test_invented_number_is_flagged", "test_llm_output_is_validated"]),
    ("G02", "References / source links", "Every claim resolves", ["test_g02_", "test_every_fact_has_provenance", "test_analysis_returns_metrics_with_evidence"]),
    ("E01", "Complete demo user journey", "PDF exported without manual intervention", ["test_e01_", "test_full_upload_to_memo_flow", "test_upload_review_analyse"]),
    ("FIN-01", "Refinance cannot erase new-loan interest", "Regression example and API test", ["test_fin01_", "test_rate_cut_cannot", "test_amortizing_facility"]),
    ("FIN-02", "Restricted cash handled explicitly", "Source reconciliation and ratio test", ["test_fin02_", "test_memo_caveats"]),
    ("FIN-03", "Non-USD upload not scored by USD-trained model", "Gated model test", ["test_fin03_"]),
    ("DATA-01", "Missing/rejected critical figures, impossible dates", "Upload and API tests", ["test_data01_", "test_unknown_fact_field", "test_malformed_upload", "test_upload_of_uncurated", "test_gate_blocks"]),
    ("WF-01", "Sample company -> memo -> PDF first try", "Browser smoke test", ["test_e01_"]),
    ("WF-02", "Changed loan -> memo stale -> regenerate", "Browser/API test", ["test_wf02_", "test_e01_"]),
    ("ML-01", "Model X-Ray matches frozen metadata, honest benchmarks", "Metadata consistency test", ["test_ml01_"]),
    ("ML-02", "Replay from held-out rows, no future leakage", "Date/split invariant test", ["test_ml02_"]),
    ("OUT-01", "Three demo borrowers reconcile to original filings", "Manual cross-check + test", ["test_out01_", "test_r6_", "test_r7_", "test_model_scores_unchanged", "test_both_templates_match_sec"]),
    ("OUT-02", "Key memo numbers trace to statements and inputs", "Four citation drilldowns", ["test_out02_"]),
    ("E1", "Memo semantic checks and structure", "Direction, signed headroom, undefined ratios, case mixing", ["test_direction_", "test_negative_headroom", "test_positive_headroom", "test_undefined_ratio", "test_scenario_assumptions", "test_template_memo_passes", "test_refinancing_memo"]),
    ("C3", "Neural score separate from loan stress", "Sliders never change the score", ["test_c3_", "test_e01_"]),
    ("F", "Stress heatmap from the Python engine", "One engine call per cell, matches loan table", ["test_grid_", "test_every_cell_", "test_rate_shock_moves"]),
    ("HYG", "Upload privacy hygiene", "Uploads unlisted; audit operator-only", ["test_full_upload_to_memo_flow", "test_security_headers"]),
    ("A11Y", "WCAG 2.1 AA (axe-core)", "No serious/critical violations", ["test_wcag_aa"]),
    ("SEC", "Security controls", "Validation, limits, headers, deletion", ["test_rejects_non_pdf", "test_upload_rate_limit", "test_security_headers", "test_unexpected_errors_hide", "test_cors_"]),
]


def main():
    xml = Path("/tmp/creditlens-junit.xml")
    rc = subprocess.call([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={xml}"])
    cases = []
    for tc in ET.parse(xml).iter("testcase"):
        status = "skipped" if tc.find("skipped") is not None else "failed" if (tc.find("failure") is not None or tc.find("error") is not None) else "passed"
        cases.append((tc.get("name"), status))
    total = {s: sum(1 for _, x in cases if x == s) for s in ("passed", "failed", "skipped")}
    L = ["# Test matrix (Blueprint p.22)", "",
         f"_Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC by `scripts/test_matrix.py`: "
         f"{total['passed']} passed, {total['failed']} failed, {total['skipped']} skipped "
         f"(browser tests run only with `E2E_BASE_URL`)._", "",
         "| ID | Check | Pass condition | Tests | Result |", "|---|---|---|---|---|"]
    for tid, check, cond, pats in MATRIX:
        hits = [(n, s) for n, s in cases if any(n.startswith(p) or p in n for p in pats)]
        ran = [s for _, s in hits if s != "skipped"]
        res = "✅ pass" if ran and all(s == "passed" for s in ran) else "❌ fail" if "failed" in ran else "⏭ not run"
        L.append(f"| {tid} | {check} | {cond} | {len(hits)} | {res} |")
    L += ["", "## Release acceptance (Blueprint p.22)", "",
          "| Condition | Evidence |", "|---|---|",
          "| 100% of critical arithmetic unit tests pass | F01–F04, S01 rows above; `docs/scenario_crosscheck.xlsx` reconciliation |",
          "| Neural model evaluated on held-out data with documented limitations | `training/model_card/stress_mlp_v1.md`, Model X-Ray page |",
          "| Displayed figures traceable to inputs, formula and model versions | G02; evidence rail; memo appendix |",
          "| 3 curated cases demo-stable; 2 report formats upload and review | E01; `tests/fixtures/*.pdf` templates (D02, D03) |",
          "| Memo validation reports zero unsupported numerical claims; user can correct and regenerate | G01; memo edit tests |"]
    Path("docs/test_matrix.md").write_text("\n".join(L) + "\n")
    print("\n".join(L[:30]))
    sys.exit(rc)


if __name__ == "__main__":
    main()
