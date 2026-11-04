import os
from pathlib import Path

# API tests run against the synthetic fixture, not the real curated companies.
os.environ.setdefault("CREDITLENS_CURATED", str(Path(__file__).parent / "fixtures"))
