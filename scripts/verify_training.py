"""Re-train the baselines and the deployed network from the frozen panel and check they match what is committed.

    python -m scripts.verify_training            # ~5-10 min on 2 cores; writes only to a scratch folder

Nothing committed is overwritten: results go to a temporary folder and the network is exported there too. The
check compares the re-trained test predictions (all 1,086 held-out rows) and the exported network weights with the
committed ones. Bit-identical results are expected on the same library versions; other CPUs or BLAS builds can
differ in the last digits, so predictions are compared with a tolerance and the largest difference is printed.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

TOL = 1e-6


def compare_csv(new: Path, old: Path, cols: list[str]) -> float:
    a = pd.read_csv(new, dtype={"cik": str}).sort_values(["cik", "fiscal_year_end"]).reset_index(drop=True)
    b = pd.read_csv(old, dtype={"cik": str}).sort_values(["cik", "fiscal_year_end"]).reset_index(drop=True)
    assert len(a) == len(b) and (a[["cik", "fiscal_year_end"]] == b[["cik", "fiscal_year_end"]]).all().all()
    return float(max(np.abs(a[c] - b[c]).max() for c in cols))


def network_predictions(artifact: Path, out_csv: Path) -> None:
    """Score the 1,086 test rows with an exported network, exactly as the app and export_replay do."""
    import yaml
    from backend.app.models.inference import StressModel
    from training.ml.export_replay import score_test
    base = yaml.safe_load(Path("configs/experiment_baselines_v1.yaml").read_text())
    te = score_test(StressModel.load(artifact), base)
    te[["cik", "fiscal_year_end", "mlp"]].to_csv(out_csv, index=False, float_format="%.17g")


def main() -> int:
    reuse = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--reuse=")), None)
    tmp = Path(reuse) if reuse else Path(tempfile.mkdtemp(prefix="creditlens-verify-"))
    run = lambda *a: subprocess.run([sys.executable, "-m", *a], check=True)  # noqa: E731
    print(f"scratch folder: {tmp}")
    if not reuse:
        run("training.ml.run_baselines", "--out", str(tmp / "baselines_v1"))
        run("training.ml.train_mlp", "--out", str(tmp / "mlp_v1"), "--artifact-dir", str(tmp / "stress_mlp_v1"))
    network_predictions(tmp / "stress_mlp_v1", tmp / "mlp_v1/test_predictions_label_next_fy.csv")
    checks = {
        "baseline test predictions": compare_csv(tmp / "baselines_v1/test_predictions_label_next_fy.csv",
                                                 Path("training/experiments/baselines_v1/test_predictions_label_next_fy.csv"),
                                                 ["rule_score", "logistic", "xgboost"]),
        "network test predictions": compare_csv(tmp / "mlp_v1/test_predictions_label_next_fy.csv",
                                                Path("training/experiments/mlp_v1/test_predictions_label_next_fy.csv"), ["mlp"]),
    }
    new_w = np.load(tmp / "stress_mlp_v1/weights.npz")
    old_w = np.load("backend/models/stress_mlp_v1/weights.npz")
    checks["network weights"] = float(max(np.abs(new_w[k] - old_w[k]).max() for k in old_w.files))
    ok = True
    for name, diff in checks.items():
        status = "identical" if diff == 0 else ("match" if diff < TOL else "DIFFERENT")
        ok &= diff < TOL
        print(f"{name:28s} max |difference| = {diff:.3g}  -> {status}")
    print("VERIFIED: re-training reproduces the committed model and predictions" if ok else "NOT VERIFIED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
