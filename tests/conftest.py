import os

# Never read the developer's real .env (API keys) during tests; strip provider keys too.
os.environ["PTK_SKIP_DOTENV"] = "1"
for _k in ("PERPLEXITY_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "SCRAPECREATORS_API_KEY", 
           "APIFY_TOKEN", "APIFY_API_TOKEN", "RUN_BUDGET_USD"):
    os.environ.pop(_k, None)

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "quantitative_samples"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def expected() -> dict:
    return json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))
