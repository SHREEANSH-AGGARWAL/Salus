"""
Durable Write-Ahead Log (WAL) for Raft consensus using SQLite in WAL mode.

Provides ACID persistence for:
    1. Raft metadata: current_term, voted_for (must survive crashes §5.2)
    2. Raft log entries: append, query, and conflict truncation (§5.3)
    3. State machine snapshots: for log compaction (§7)

Uses standard library sqlite3 with:
    PRAGMA journal_mode=WAL;
    PRAGMA synchronous=NORMAL;
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import structlog

from salus.raft.log_entry import CommandType, LogEntry

logger = structlog.get_logger()


class WALManager:
    """SQLite-backed persistent Write-Ahead Log.

    Thread-safe and process-safe with SQLite WAL mode.
    """

    def __init__(self, db_dir: str | Path, node_id: str = "node") -> None:
        self.db_dir = Path(db_dir)
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.db_dir / f"raft_{node_id}.db"
        self.node_id = node_id

        self._conn = sqlite3.connect(
            str(self.db_path),
            isolation_level=None,
            check_same_thread=False,
        )
        self._init_db()

    def _init_db(self) -> None:
        """Initialize tables and WAL pragmas."""
        cur = self._conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA synchronous=NORMAL;")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS raft_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS raft_log (
                log_index INTEGER PRIMARY KEY,
                term INTEGER NOT NULL,
                command_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                timestamp TEXT NOT NULL
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS raft_snapshot (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                last_index INTEGER NOT NULL,
                last_term INTEGER NOT NULL,
                data BLOB NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        self._conn.commit()

    # ========================================================================
    # Metadata (§5.2) — current_term, voted_for
    # ========================================================================

    def save_meta(self, term: int, voted_for: str | None) -> None:
        """Atomically persist current_term and voted_for before responding to RPCs."""
        cur = self._conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO raft_meta (key, value) VALUES ('current_term', ?);",
            (str(term),),
        )
        cur.execute(
            "INSERT OR REPLACE INTO raft_meta (key, value) VALUES ('voted_for', ?);",
            (voted_for if voted_for is not None else "",),
        )
        self._conn.commit()

    def get_meta(self) -> tuple[int, str | None]:
        """Read persisted current_term and voted_for."""
        cur = self._conn.cursor()
        cur.execute("SELECT key, value FROM raft_meta WHERE key IN ('current_term', 'voted_for');")
        rows = dict(cur.fetchall())
        term = int(rows.get("current_term", 0))
        voted_for_raw = rows.get("voted_for", "")
        voted_for = voted_for_raw if voted_for_raw else None
        return term, voted_for

    # ========================================================================
    # Log Entries (§5.3)
    # ========================================================================

    def append_entry(self, entry: LogEntry) -> None:
        """Append a single log entry to disk."""
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO raft_log (log_index, term, command_type, payload, timestamp)
            VALUES (?, ?, ?, ?, ?);
            """,
            (
                entry.index,
                entry.term,
                entry.command_type.value,
                entry.payload,
                entry.timestamp.isoformat(),
            ),
        )
        self._conn.commit()

    def append_entries(self, entries: list[LogEntry]) -> None:
        """Atomically append a batch of log entries to disk."""
        if not entries:
            return
        cur = self._conn.cursor()
        cur.executemany(
            """
            INSERT OR REPLACE INTO raft_log (log_index, term, command_type, payload, timestamp)
            VALUES (?, ?, ?, ?, ?);
            """,
            [
                (
                    e.index,
                    e.term,
                    e.command_type.value,
                    e.payload,
                    e.timestamp.isoformat(),
                )
                for e in entries
            ],
        )
        self._conn.commit()

    def truncate_after(self, index: int) -> None:
        """Delete all entries after index (strictly log_index > index)."""
        cur = self._conn.cursor()
        cur.execute("DELETE FROM raft_log WHERE log_index > ?;", (index,))
        self._conn.commit()

    def read_all_entries(self) -> list[LogEntry]:
        """Read all log entries in log_index order."""
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT log_index, term, command_type, payload, timestamp
            FROM raft_log ORDER BY log_index ASC;
            """
        )
        entries: list[LogEntry] = []
        for row in cur.fetchall():
            entries.append(
                LogEntry(
                    index=row[0],
                    term=row[1],
                    command_type=CommandType(row[2]),
                    payload=row[3],
                    timestamp=datetime.fromisoformat(row[4]),
                )
            )
        return entries

    # ========================================================================
    # Snapshots (§7)
    # ========================================================================

    def save_snapshot(self, last_index: int, last_term: int, data: bytes) -> None:
        """Persist a snapshot and truncate older log entries up to last_index."""
        cur = self._conn.cursor()
        now_str = datetime.now(UTC).isoformat()
        cur.execute(
            """
            INSERT OR REPLACE INTO raft_snapshot (id, last_index, last_term, data, created_at)
            VALUES (1, ?, ?, ?, ?);
            """,
            (last_index, last_term, data, now_str),
        )
        # Compact log entries covered by the snapshot
        cur.execute("DELETE FROM raft_log WHERE log_index <= ?;", (last_index,))
        self._conn.commit()

    def get_snapshot(self) -> tuple[int, int, bytes] | None:
        """Load latest snapshot (last_index, last_term, data)."""
        cur = self._conn.cursor()
        cur.execute("SELECT last_index, last_term, data FROM raft_snapshot WHERE id = 1;")
        row = cur.fetchone()
        if row is None:
            return None
        return row[0], row[1], row[2]

    # ========================================================================
    # Recovery
    # ========================================================================

    def recover(self) -> tuple[int, str | None, list[LogEntry], tuple[int, int, bytes] | None]:
        """Complete state recovery on startup.

        Returns:
            (current_term, voted_for, log_entries, snapshot)
        """
        term, voted_for = self.get_meta()
        entries = self.read_all_entries()
        snapshot = self.get_snapshot()
        logger.info(
            "wal_recovered",
            node_id=self.node_id,
            term=term,
            voted_for=voted_for,
            entries_count=len(entries),
            has_snapshot=snapshot is not None,
        )
        return term, voted_for, entries, snapshot

    def close(self) -> None:
        """Close SQLite connection."""
        self._conn.close()
