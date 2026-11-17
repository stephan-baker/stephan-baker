import sqlite3
import time
from pathlib import Path


class Memory:
    """Historie konverzace v SQLite, ať si pamatuje i po restartu."""

    def __init__(self, path: str | Path = "memory.db"):
        self.db = sqlite3.connect(str(path))
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                ts REAL NOT NULL
            )"""
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_user ON messages(user_id, id)"
        )
        self.db.commit()

    def add(self, user_id: int, role: str, content: str) -> None:
        self.db.execute(
            "INSERT INTO messages (user_id, role, content, ts) VALUES (?, ?, ?, ?)",
            (user_id, role, content, time.time()),
        )
        self.db.commit()

    def recent(self, user_id: int, limit: int) -> list[dict]:
        rows = self.db.execute(
            "SELECT role, content, ts FROM messages WHERE user_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [{"role": r, "content": c, "ts": t} for r, c, t in reversed(rows)]

    def last_ts(self, user_id: int) -> float | None:
        row = self.db.execute(
            "SELECT ts FROM messages WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        return row[0] if row else None

    def reset(self, user_id: int) -> None:
        self.db.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
        self.db.commit()
