"""Freeze a release (Blueprint p.20, Week 8): checksum every data, model and config artifact.

    python scripts/freeze_release.py 1.0.0

Writes release/manifest.json. tests/unit/test_release_manifest.py recomputes the hashes, so any
change to a frozen artifact fails CI until it is re-frozen on purpose (new version).
"""
import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

FROZEN = [
    "configs/*.yaml",
    "training/data/universe_v1.csv",
    "training/data/panel_v1.csv",
    "training/data/reports/coverage_v1.md",
    "training/experiments/baselines_v1/results.json",
    "training/experiments/mlp_v1/results.json",
    "backend/models/stress_mlp_v1/*",
    "backend/data/curated/*",
    "docs/scenario_crosscheck.xlsx",
    "tests/fixtures/*.pdf",
    "requirements-api.txt",
    "requirements-ml.txt",
    "frontend/package-lock.json",
]

REPRODUCE = [
    "pip install -r requirements-ml.txt && pip install torch --index-url https://download.pytorch.org/whl/cpu",
    "python -m training.pipeline.universe --target 600          # SEC frames + submissions (needs SEC_USER_AGENT)",
    "python -m training.features.build_panel --universe training/data/universe_v1.csv --out training/data/panel_v1.csv --report training/data/reports/coverage_v1.md",
    "python -m training.ml.run_baselines --config configs/experiment_baselines_v1.yaml",
    "python -m training.ml.train_mlp --config configs/experiment_mlp_v1.yaml",
    "python -m training.ml.export_xray",
    "python scripts/test_matrix.py",
]


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def files() -> list[Path]:
    out = []
    for pat in FROZEN:
        out += sorted(p for p in Path(".").glob(pat) if p.is_file())
    return out


def main(version: str):
    meta = json.loads(Path("backend/models/stress_mlp_v1/metadata.json").read_text())
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    manifest = {
        "version": version,
        "frozen_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "frozen_from_commit": commit,
        "python": platform.python_version(),
        "model": {k: meta[k] for k in ("model", "target", "label_version", "feature_version", "selected_config",
                                       "n_seeds", "trained_at")},
        "test_metrics": {"mlp_pr_auc": meta["test_metrics_calibrated"]["pr_auc"],
                         "mlp_pr_auc_ci95": meta["test_bootstrap"]["pr_auc_ci95"],
                         "xgboost_pr_auc": meta["xgboost_test_pr_auc"]},
        "files": {str(p): sha256(p) for p in files()},
        "reproduce": REPRODUCE,
    }
    Path("release").mkdir(exist_ok=True)
    Path("release/manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(f"froze {len(manifest['files'])} files as v{version}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "1.0.0")
