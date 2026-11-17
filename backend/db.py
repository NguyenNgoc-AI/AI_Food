import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def transaction(write=False):
    path = Path(os.environ.get("SMARTFOOD_DB", ROOT / "var" / "smartfood.sqlite3"))
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        yield conn
        conn.commit()
    finally:
        conn.close()


def migrate():
    with transaction(write=True) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 1:
            return
        if version != 0:
            raise RuntimeError(f"Phiên bản schema chưa được hỗ trợ: {version}")
        script = (ROOT / "migrations" / "001_foundation.sql").read_text(encoding="utf-8")
        statement = ""
        for line in script.splitlines(keepends=True):
            statement += line
            if sqlite3.complete_statement(statement):
                conn.execute(statement)
                statement = ""
        if statement.strip():
            raise RuntimeError("Migration chưa hoàn chỉnh")
        conn.execute("PRAGMA user_version = 1")


if __name__ == "__main__":
    migrate()
