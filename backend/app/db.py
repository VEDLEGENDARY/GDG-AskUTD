"""SQLite persistence for request analytics and user feedback."""
from __future__ import annotations

import argparse
import csv
import io
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .config import Settings


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


@contextmanager
def connection(path: Path):
    """Commit successful operations and always close the SQLite handle."""
    db = connect(path)
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def initialize(path: Path) -> None:
    with connection(path) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS requests (
                request_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                question TEXT NOT NULL,
                abstained INTEGER NOT NULL,
                latency_ms INTEGER NOT NULL,
                citation_count INTEGER NOT NULL,
                retriever TEXT NOT NULL,
                llm TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL REFERENCES requests(request_id),
                rating TEXT NOT NULL CHECK (rating IN ('up', 'down')),
                comment TEXT,
                created_at TEXT NOT NULL
            );
        """)


def save_request(path: Path, *, request_id: str, question: str, abstained: bool,
                 latency_ms: int, citation_count: int, retriever: str, llm: str) -> None:
    with connection(path) as db:
        db.execute("""INSERT INTO requests
            (request_id, created_at, question, abstained, latency_ms, citation_count, retriever, llm)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (request_id, datetime.now(timezone.utc).isoformat(), question, int(abstained), latency_ms,
             citation_count, retriever, llm))


def save_feedback(path: Path, request_id: str, rating: str, comment: str | None) -> bool:
    with connection(path) as db:
        exists = db.execute("SELECT 1 FROM requests WHERE request_id=?", (request_id,)).fetchone()
        if not exists:
            return False
        db.execute("INSERT INTO feedback(request_id, rating, comment, created_at) VALUES (?, ?, ?, ?)",
                   (request_id, rating, comment, datetime.now(timezone.utc).isoformat()))
        return True


def export_csv(path: Path) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(("request_id", "created_at", "question", "abstained", "latency_ms",
                     "citation_count", "retriever", "llm", "feedback_count", "up_count", "down_count"))
    if not path.exists():
        return output.getvalue()
    with connection(path) as db:
        rows = db.execute("""SELECT r.*, COUNT(f.id) AS feedback_count,
            SUM(CASE WHEN f.rating='up' THEN 1 ELSE 0 END) AS up_count,
            SUM(CASE WHEN f.rating='down' THEN 1 ELSE 0 END) AS down_count
            FROM requests r LEFT JOIN feedback f USING(request_id)
            GROUP BY r.request_id ORDER BY r.created_at""").fetchall()
        for row in rows:
            writer.writerow(tuple(row[k] or 0 if k in {"feedback_count", "up_count", "down_count"} else row[k]
                                  for k in row.keys()))
    return output.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", action="store_true", help="print request and feedback summary as CSV")
    args = parser.parse_args()
    path = Settings.from_env().database_path
    if args.export:
        print(export_csv(path), end="")
    else:
        initialize(path)


if __name__ == "__main__":
    main()
