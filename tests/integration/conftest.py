"""Shared API test environment: temp SQLite + storage, inline jobs. Set before the app imports."""
import os
import shutil
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="ptk-api-"))
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", f"sqlite:///{_TMP / 'test.db'}")
os.environ["STORAGE_ROOT"] = str(_TMP / "storage")
os.environ["JOB_BACKEND"] = "eager"
HAS_RENDER = bool(shutil.which("docker")) and os.environ.get("SKIP_RENDER") != "1"
os.environ.setdefault("RENDER_BACKEND", "docker" if HAS_RENDER else "none")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c
