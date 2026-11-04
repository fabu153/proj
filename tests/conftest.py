import os
import tempfile
from pathlib import Path

# API tests run against the synthetic fixture and a throwaway database, never real uploads.
os.environ.setdefault("CREDITLENS_CURATED", str(Path(__file__).parent / "fixtures"))
os.environ.setdefault("CREDITLENS_DB", os.path.join(tempfile.mkdtemp(prefix="creditlens-test-"), "test.db"))
os.environ.setdefault("CREDITLENS_LLM_PROVIDER", "none")   # tests never call a paid API
