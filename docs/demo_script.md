# Demo script — 3 minutes (Blueprint p.24)

Fallback: `release/creditlens_demo.mp4` (1:45, captioned, recorded from this exact flow). If the live site
misbehaves for more than ten seconds, switch to the video and keep talking over it.

## Pre-flight (10 minutes before)

1. Open `https://creditlens-api-mgcf.onrender.com/health` — wait until it says `"status":"ok"` (wakes the free
   Render instance; first call can take ~60 s).
2. Open three tabs: the start page (`/`), the Model X-Ray (`/model`), and the upload page (`/upload`).
3. On the start page, open **United Rentals** once so its data is cached.
4. Have `tests/fixtures/ar_thousands.pdf` on the desktop for the upload step.
5. Have the video open in a player, paused at 0:00.

## Run of show

| Time | Do | Say (point demonstrated) |
|---|---|---|
| 0:00–0:25 | Start page → **Explore a sample company** → **United Rentals**. Point at the progress steps. | "CreditLens screens a borrower for a USD 100m facility. Everything here comes from the company's SEC 10-K filings — no typing, no copy-paste. The steps at the top track the file from company to committee memo." *(real data enters)* |
| 0:25–0:55 | Click **Net debt / EBITDA** in the ledger. Point at the right rail, then at the D&A source. | "1.94x. Here's the formula, its inputs, and the exact 10-K accession for each input. We reconciled the three sample companies against the original 10-Ks: United Rentals reports rental-fleet depreciation inside cost of revenue, so a rule adds it back — EBITDA is 7,081, not 4,411. Every figure on screen has this trail." *(traceable sources, deterministic formulas)* |
| 0:55–1:25 | Scroll to **Neural screen** (1.8%, low). Switch to the Model X-Ray tab. | "A PyTorch network trained on 1,626 company-years filed 2009–18 estimates next-year accounting stress. Tested once on 2021–25 filings: PR-AUC 0.805 against 0.825 for XGBoost — statistically level, and we say so. It clearly beats the simple rule." *(real deep learning, honest evaluation)* |
| 1:25–2:05 | Back to the workspace → **Loan lab**. EBITDA slider to −20%, rate shock to +200 bp. Then set the max net debt / EBITDA covenant to 2.25x. Point at the covenant ruler and the steps list. | "Add the facility, stress it. EBITDA down 20%, rates up 200 bp: net debt / EBITDA rises to 2.45x — inside a 3.5x covenant. Tighten the covenant to 2.25x and the same stress breaches it. Every step of the arithmetic is listed — and it reconciles exactly to an independent Excel model." *(real loan computations)* |
| 2:05–2:35 | **Draft credit memo**. Click a citation number. Change the facility amount: point at "Outdated — regenerate", click it. Edit a sentence to add "margins will reach 45%". | "The memo writer can't type numbers — it places references; the engines fill them in. Click a citation and you get its source. The memo, the table and the PDF share one snapshot id, so if I change the loan the memo is marked outdated until I regenerate. If I invent a figure, it's flagged and kept out of the PDF." *(evidence-constrained generative AI)* |
| 2:35–3:00 | **Download PDF**, then close. | "Committee-ready PDF with every assumption, the snapshot id and an evidence appendix. It's decision support: no rating, no default probability, analyst review required. Limitations are on the Model X-Ray page." *(decision-support positioning)* |

Optional (+40 s, if time allows): Upload page → `ar_thousands.pdf` with CIK `1278027` → accept the flagged
net-interest line → **Analyse reviewed figures** → same 11.59x leverage as the SEC data, now cited to report pages.

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

**How good is the data?** Period selection agrees with SEC's own aggregates on 99.4–99.7% of 2,560 like-for-like
comparisons; the three sample issuers were also reconciled line by line against their original 10-Ks
(`docs/manual_cross_check.md`), which found and fixed the United Rentals D&A and the cash-interest issue; 32 defects
found and fixed are in `docs/defects.md`.

**Why does the neural screen use different D&A for United Rentals than the ratios?** The network was trained and
evaluated on the v1.0 input definitions across 1,626 company-years. Feeding it corrected definitions for three
companies would score them on inputs it never saw. The credit ratios use the corrected figures; the screen keeps
its training basis until a documented retrain.
