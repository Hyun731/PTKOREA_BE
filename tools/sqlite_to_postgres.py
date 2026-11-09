"""Copy every row from a SQLite DB (local dev/Docker) into an empty, migrated Postgres DB.

    python -m tools.sqlite_to_postgres var/dev.db postgresql+psycopg://ptk:PW@host:5432/ptk [--replace]

- The source file is never modified: it is copied to a temp file and that copy is
  upgraded to the latest migration first, so both sides have the same schema.
- The target must already be at `alembic upgrade head` (the prod stack does this on start).
- Without --replace the target must be empty; with it, target tables are emptied first.
- Uploaded files/outputs are not in the DB: copy the `var/` folder (storage etc.) separately.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from sqlalchemy import Integer, create_engine, func, select, text

ROOT = Path(__file__).resolve().parents[1]
BATCH = 1000


def _upgraded_copy(src: Path, tmpdir: Path) -> Path:
    dst = tmpdir / "source.db"
    # sqlite3 backup API folds the WAL in and is safe while the app is running.
    with sqlite3.connect(src) as a, sqlite3.connect(dst) as b:
        a.backup(b)
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{dst}", "PTK_SKIP_DOTENV": "1"}
    subprocess.run(
        [sys.executable, "-c", "from app.migrate import upgrade_to_head; upgrade_to_head()"],
        cwd=ROOT, env=env, check=True,
    )
    return dst


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sqlite_path", type=Path)
    ap.add_argument("postgres_url")
    ap.add_argument("--replace", action="store_true", help="empty target tables before copying")
    args = ap.parse_args()

    if not args.sqlite_path.is_file():
        ap.error(f"no such file: {args.sqlite_path}")
    if not args.postgres_url.startswith("postgresql"):
        ap.error("target must be a postgresql+psycopg:// URL")

    os.environ.setdefault("PTK_SKIP_DOTENV", "1")
    from app.models import Base  # noqa: E402  (after env is set)

    tables = [t for t in Base.metadata.sorted_tables if t.name != "alembic_version"]

    with tempfile.TemporaryDirectory() as tmp:
        src = create_engine(f"sqlite:///{_upgraded_copy(args.sqlite_path, Path(tmp))}")
        dst = create_engine(args.postgres_url)

        with dst.begin() as conn:
            busy = [t.name for t in tables if conn.execute(select(func.count()).select_from(t)).scalar()]
            if busy and not args.replace:
                print(f"target is not empty ({', '.join(busy)}); use --replace to overwrite", file=sys.stderr)
                return 2
            if busy:
                names = ", ".join(f'"{t.name}"' for t in tables)
                conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))

            with src.connect() as sconn:
                for t in tables:
                    n = 0
                    rows = sconn.execute(select(t)).mappings()
                    while chunk := rows.fetchmany(BATCH):
                        conn.execute(t.insert(), [dict(r) for r in chunk])
                        n += len(chunk)
                    print(f"{t.name:28s} {n:>8d}")

            # Integer autoincrement PKs: move each sequence past the copied ids.
            for t in tables:
                for c in t.primary_key.columns:
                    if isinstance(c.type, Integer) and c.autoincrement in (True, "auto"):
                        conn.execute(text(
                            f"SELECT setval(pg_get_serial_sequence('\"{t.name}\"', '{c.name}'), "
                            f"COALESCE((SELECT MAX(\"{c.name}\") FROM \"{t.name}\"), 0) + 1, false)"
                        ))
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
