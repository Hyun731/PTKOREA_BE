"""Apply Alembic migrations at startup (dev/test SQLite). Postgres deployments run
`alembic upgrade head` explicitly before starting the API."""
from __future__ import annotations


from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.config import ROOT, settings
from app.db import engine

BASELINE = "c965cabe5f2a"  # initial schema; databases made by the old create_all are stamped here


def upgrade_to_head() -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    tables = set(inspect(engine).get_table_names())
    if "projects" in tables and "alembic_version" not in tables:
        command.stamp(cfg, BASELINE)
    command.upgrade(cfg, "head")
