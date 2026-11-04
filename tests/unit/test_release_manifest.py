"""Frozen release: every artifact listed in release/manifest.json still has its recorded SHA-256."""
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
MANIFEST = ROOT / "release" / "manifest.json"
pytestmark = pytest.mark.skipif(not MANIFEST.exists(), reason="no frozen release yet")


def test_frozen_artifacts_unchanged():
    m = json.loads(MANIFEST.read_text())
    changed = [f for f, h in m["files"].items() if hashlib.sha256((ROOT / f).read_bytes()).hexdigest() != h]
    assert not changed, f"frozen artifacts changed without a new release: {changed}"


def test_manifest_matches_deployed_model():
    m = json.loads(MANIFEST.read_text())
    meta = json.loads((ROOT / "backend/models/stress_mlp_v1/metadata.json").read_text())
    assert m["model"]["model"] == meta["model"] and m["test_metrics"]["mlp_pr_auc"] == meta["test_metrics_calibrated"]["pr_auc"]
