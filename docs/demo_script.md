# Demo script — 3 minutes (roadmap Stage E3)

Fallback: `release/creditlens_demo.mp4` (captioned, recorded from this exact flow by `scripts/record_demo.py`). If the
live site misbehaves for more than ten seconds, switch to the video and keep talking over it.

## Pre-flight (10 minutes before, in a fresh browser window)

1. Open `https://creditlens-api-mgcf.onrender.com/health` and wait for `"status":"ok"`. The free Render instance
   sleeps; the first call can take about a minute. The site itself also shows a wake-up message with "Try again".
2. Open the start page (`/`), the Model X-Ray (`/model`) and the replay (`/replay`) in three tabs.
3. On the start page, open **Procter & Gamble** once so its data is cached.
4. Look up the day's EUR/USD rate from a public source and note it with today's date. The video uses an
   illustrative 1.08; if FX would distract, keep the facility in USD.
5. Have the video open in a player, paused at 0:00.

## Run of show

| Time | Do | Say (point demonstrated) |
|---|---|---|
| 0:00–0:30 | Start page → **Quick demo** → **Procter & Gamble** (or type a ticker in **Search a U.S. public company**, e.g. CAT). Click **Net debt / EBITDA** in the ledger. | "CreditLens screens a borrower for a new facility. Every figure comes from the company's 10-K filings through a versioned formula: net debt over EBITDA is 1.06x, and the rail shows the inputs and the SEC accession. Amber means qualified: P&G only tags cash including restricted cash, so net debt is flagged rather than presented as clean." *(source-backed financials)* |
| 0:30–1:10 | Scroll to **Neural screen** (1.0%, low). Switch to the **Model X-Ray** tab: architecture, then *How it performed*, then *Where it fails*. | "A trained PyTorch network, 62 inputs, three hidden layers, five seeds averaged, reads the same annual report and gives a 1% chance of accounting stress next year. It was tested once on 2021–25 filings it never saw: PR-AUC 0.805 against 0.825 for XGBoost. XGBoost's point estimate is higher, and the difference is within the margin of error; we report that. It clearly beats a simple rule. Its weakness: it catches stress that persists, but only 15 of 96 new onsets." *(real deep learning, honest evaluation)* |
| 1:10–1:50 | Back to the workspace → **Loan lab**. Currency **EUR**: point at the refusal. Enter the rate and its date. EBITDA slider −30%, rate shock +200 bp. Point at the covenant ruler, then the heatmap. | "A EUR 100 million facility against dollar statements: the engine refuses to mix currencies until I give a dated rate. With EBITDA down 30% and rates up 200 bp, net debt over EBITDA is 1.52x, far inside a 3.5x covenant; for P&G this loan is small. The heatmap runs the same Python engine 42 times; click a cell to load it." *(real loan computations)* |
| 1:50–2:25 | **Draft credit memo**. Point at the header block, click a figure (underlined) to open its source trail. Change the amount: point at **Outdated — regenerate**, click it. **Download PDF**. | "The memo opens with borrower, facility, purpose and review status. The writer cannot type numbers; the engines insert them. Click a figure and you get filing, normalized fact, calculation and the sentence that uses it. The memo shares the loan lab's snapshot id, so if I change the loan it is marked outdated until regenerated. The PDF prints every assumption and the snapshot id." *(evidence-constrained generative AI)* |
| 2:25–3:00 | **Model replay** tab → Example 3 (**Jazz Pharmaceuticals**, FY2021). Read the forecast, then **Reveal next-year outcome**. | "This is what the network said when Jazz's 2021 annual report was filed, before anyone knew what came next: 76%, high. Reveal: accounting stress followed, and among held-out companies scored in that range 75% did. The same page has a false alarm and a miss, because we show its mistakes too. Decision support, not a decision." *(genuine out-of-sample performance)* |

Optional (+40 s): Upload page → `tests/fixtures/ar_thousands.pdf` with CIK `1278027` → accept the flagged
net-interest line → **Analyse reviewed figures** → the same 11.59x as the SEC data, now cited to report pages.

**Quality gate before presenting:** run `E2E_BASE_URL=<site> E2E_API_URL=<api> pytest tests/end_to_end` from a fresh
browser session. All browser tests must pass, including the start-to-PDF journey, the stale-memo check, the replay
reveal and the accessibility scans.

## Questions to prepare for (answers with our numbers)

**Why an MLP instead of XGBoost?** The course asks for a trained neural network; we treat simpler models as strict
baselines. Result: MLP 0.805 vs XGBoost 0.825 test PR-AUC; paired company-bootstrap difference −0.020 (95% CI −0.044 to
+0.006) — not reliably different. We report it rather than hide it, and deploy the MLP with XGBoost shown beside it.

**How do you prevent look-ahead?** Features are dated by the 10-K filing date; labels come only from year t+1 and
carry their own publication date; the split is by filing date (train 2009–18, validation 2019–20, test 2021–25) with a
purge that drops training labels published after validation starts; the original reported vintage is used (8.9% of
values were later restated). Test was evaluated once.

**Is this a real PD?** No. It is a pre-registered accounting-stress proxy: at least two of EBIT cover < 1.5x,
debt/EBITDA > 5x, negative operating cash flow, in the next fiscal year. The UI and memo never say "default".

**What if data is missing?** Missing stays missing: ratios show "n/a" with a reason; undeterminable labels are dropped,
not set to 0; the score is withheld when the company is outside the population or more than 12 of 31 inputs are
missing; uploaded figures with low confidence must be reviewed before analysis.

**What does AI do versus Python?** The network learns a risk function from 1,626 training company-years; Python
computes every ratio and scenario (reconciled to Excel to 1e-9); the language model only arranges sentences around
numbered references, and a validator rejects any figure it cannot trace.

**Why did prevalence rise in the test window?** 21.5% in training vs 29.7% in test — a harder post-2021 regime (rates,
inflation). Calibration was fitted on 2019–20, so the model somewhat understates risk later; shown on the calibration
chart.

**Does the slider change the neural score?** No. The network predicts from the filed accounts; the loan lab reworks
financing mechanically. Recomputing all 31 inputs for a hypothetical company has not been validated, so the score
is shown separately and a browser test checks it never moves.

**How do you know the replay isn't cherry-picked or leaked?** The cases are chosen by a fixed rule in the code.
The forecasts are the frozen test predictions; re-running the frozen network reproduces the recorded PR-AUC to the
last digit. Every case was filed in the test window, within four months of year-end, and its outcome was published
about a year later. The outcome is only fetched when you click "Reveal".

**How good is the data?** Period selection agrees with SEC's own aggregates on 99.4–99.7% of 2,560 like-for-like
comparisons; the three sample issuers were also reconciled line by line against their original 10-Ks
(`docs/manual_cross_check.md`), which found and fixed the United Rentals D&A and the cash-interest issue; 32 defects
found and fixed are in `docs/defects.md`.

**Why does the neural screen use different D&A for United Rentals than the ratios?** The network was trained and
evaluated on the v1.0 input definitions across 1,626 company-years. Feeding it corrected definitions for three
companies would score them on inputs it never saw. The credit ratios use the corrected figures; the screen keeps
its training basis until a documented retrain.
