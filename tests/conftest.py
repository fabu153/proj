import os
import sys
import tempfile
from pathlib import Path

import pytest

# API tests run against the synthetic fixture and a throwaway database, never real uploads.
os.environ.setdefault("CREDITLENS_CURATED", str(Path(__file__).parent / "fixtures"))
os.environ.setdefault("CREDITLENS_DB", os.path.join(tempfile.mkdtemp(prefix="creditlens-test-"), "test.db"))
os.environ.setdefault("CREDITLENS_LLM_PROVIDER", "none")   # tests never call a paid API
# no test ever reaches SEC: unknown CIKs and searches are answered by the mocked responses in tests/fixtures/sec
os.environ.setdefault("CREDITLENS_SEC_FIXTURES", str(Path(__file__).parent / "fixtures" / "sec"))
os.environ.setdefault("CREDITLENS_SEC_CACHE", tempfile.mkdtemp(prefix="creditlens-sec-test-"))


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    """Every test starts with an empty rate-limit table, so no result depends on how many requests ran before it.
    Only when a test module loaded the app: unit and browser tests never import it for this."""
    main = sys.modules.get("backend.app.api.main")
    if main is not None:
        main._hits.clear()
    yield
