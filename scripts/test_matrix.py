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
    ("FIX-1", "Fiscal-year columns mapped by heading", "Same t / t-1 in any column order; ambiguity flagged", ["test_same_statements_give_identical", "test_mixed_column_counts", "test_out_of_order_headings", "test_repeated_year_heading", "test_statements_from_different_years", "test_existing_fixtures_unchanged"]),
    ("FIX-2", "Negative / zero EBITDA stress convention", "base + |base| x shock; zero never shocked", ["test_shock_moves_ebitda", "test_downside_never_improves", "test_positive_ebitda_unchanged", "test_zero_ebitda_shock", "test_negative_ebitda_trail"]),
    ("FIX-3", "Covenant PASS / BREACH / NOT TESTABLE", "Not testable never a breach; all outputs agree", ["test_positive_ebitda_pass_and_breach", "test_nonpositive_ebitda_leverage", "test_negative_ebitda_interest_cover", "test_contractual_policy", "test_zero_interest_cover", "test_missing_interest_blocks", "test_table_heatmap_memo_and_pdf_agree", "test_validator_rejects_calling"]),
    ("FIX-4", "No outdated memo exported as current", "PDF only when memo snapshot = lab snapshot", ["test_current_memo_exports", "test_any_input_change_blocks", "test_late_memo_for_old_inputs", "test_invalid_inputs_produce_no_snapshot", "test_fix4_"]),
    ("SRCH", "Search any U.S. public company (SEC mocked)", "Find, analyse, stress and export a sourced memo", ["test_exact_ticker", "test_partial_name", "test_cik_with_or_without", "test_similar_names", "test_one_entry_per_company", "test_empty_invalid", "test_index_is_fetched_once", "test_browser_never_needs_sec", "test_selection_resolves", "test_point_in_time_and_original_vintage", "test_stress_and_memo_for_a_searched", "test_search_keyboard_only", "test_search_states_and_stale"]),
    ("SRCH-O", "Searched-company outcomes", "Full / partial / score withheld / no statements / SEC down", ["test_financial_sector_filer", "test_filer_without_us_gaap", "test_filer_without_any_xbrl", "test_unknown_cik", "test_some_metrics_unavailable", "test_sec_rate_limit", "test_sec_network_failure", "test_sec_refusing_the_user_agent", "test_a_cached_list", "test_curated_samples_and_uploads_untouched", "test_searched_company_outcomes"]),
    ("RES-ON", "Onset GRU research (not deployed)", "Canonical cohort, point-in-time history, numbers reproducible", ["test_onset_cohort_is_canonical", "test_history_is_point_in_time", "test_missing_years_are_never_read", "test_sequences_put_year_t_last", "test_published_numbers_follow", "test_experiment_never_writes"]),
    ("ONSET", "One canonical onset definition (label_onset)", "6 of 73 everywhere; 15 of 96 reconciled and labelled; frozen files unchanged", ["test_reconciliation_of_96_and_73", "test_frozen_files_keep_their_original", "test_history_experiments_use_the_canonical", "test_research_file_matches_its_sources", "test_research_file_regenerates", "test_docs_no_longer_present"]),
    ("WATCH", "Watch-list threshold research (not deployed)", "Thresholds from validation scores only; counts reproducible; not in the app", ["test_watchlist_thresholds_come_from_validation", "test_watchlist_is_not_in_the_app"]),
    ("XRAY-R", "Model X-Ray experimental research section", "Overall and onset tables separate; deployed vs experimental marked; no new score", ["test_model_xray_serves_research", "test_model_xray_research_section"]),
    ("POL-151", "v1.5.1 review polish", "Banks flagged, no lab calls when unavailable, heatmap default", ["test_financial_sector_filer", "test_operating_company_has_industry", "test_bank_shows_banner", "test_heatmap_opens_on_interest_cover"]),
    ("PEER", "Peer percentiles", "Correct group fallback, self excluded, 52/53-week years, lending population only", ["test_percentile_in_own_major_group", "test_small_group_widens", "test_unknown_sic_uses_all", "test_each_peer_counts_once", "test_52_53_week_year_label", "test_real_peer_table"]),
    ("MAT", "Debt maturity wall and runway", "Matches the filing; nothing filled in; model basis untouched", ["test_maturity_wall_coverage", "test_maturity_wall_negative_fcf", "test_maturity_wall_unavailable", "test_united_rentals_maturity_wall", "test_supplement_never_changes_the_model_basis"]),
    ("CLASSIC", "Altman Z'' and Ohlson O", "Formulas by hand; point-in-time inputs; benchmark numbers reproducible", ["test_altman_z2_by_hand", "test_altman_zone_cut_offs", "test_missing_input_is_never_filled", "test_ohlson_o_by_hand", "test_deflator_uses", "test_textbook_scores_and_peer_bands", "test_classic_benchmark_numbers", "test_panel_scores_use_the_app_formulas", "test_bank_gets_no_industrial_extras", "test_v16_peers_maturities_and_textbook_scores"]),
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
