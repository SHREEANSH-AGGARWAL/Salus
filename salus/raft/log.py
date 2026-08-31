"""
Raft persistent log — write-ahead log (WAL) for log entries.

This module manages the in-memory log and provides the interface for
durable persistence. For the prototype, persistence is optional (in-memory
only with SQLite WAL for crash recovery when enabled).

Key invariants (from the paper):
    1. Log Matching Property: If two entries in different logs have the
       same index and term, they store the same command.
    2. If two entries in different logs have the same index and term,
       then the logs are identical in all preceding entries.
    3. Committed entries are never overwritten.

Reference: Ongaro & Ousterhout (2014), §5.3–§5.4
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from typing import Any

import structlog

from salus.raft.log_entry import CommandType, LogEntry

logger = structlog.get_logger()


class RaftLog:
    """In-memory Raft log with optional WAL persistence.

    The log is 1-indexed (as per the paper). Index 0 is a sentinel
    representing "before the log". All real entries start at index 1.

    Thread Safety:
        Uses a lock for concurrent access. In the prototype,
        single-threaded asyncio makes this mostly unnecessary,
        but it's here for correctness.
    """

    def __init__(self) -> None:
        # Sentinel entry at index 0 — simplifies boundary conditions
        self._entries: list[LogEntry] = [
            LogEntry(term=0, index=0, command_type=CommandType.NOOP, payload="{}")
        ]
        self._lock = threading.Lock()
        self._commit_index: int = 0
        self._last_applied: int = 0

    @property
    def commit_index(self) -> int:
        """The highest log index known to be committed (quorum ack)."""
        return self._commit_index

    @commit_index.setter
    def commit_index(self, value: int) -> None:
        if value < self._commit_index:
            raise ValueError(
                f"Cannot decrease commit index: {self._commit_index} → {value}"
            )
        self._commit_index = value

    @property
    def last_applied(self) -> int:
        """The highest log index applied to the state machine."""
        return self._last_applied

    @last_applied.setter
    def last_applied(self, value: int) -> None:
        self._last_applied = value

    @property
    def last_index(self) -> int:
        """Index of the last entry in the log."""
        return len(self._entries) - 1

    @property
    def last_term(self) -> int:
        """Term of the last entry in the log."""
        return self._entries[-1].term

    def get(self, index: int) -> LogEntry | None:
        """Get the entry at a specific index.

        Args:
            index: 1-indexed log position.

        Returns:
            The log entry, or None if index is out of range.
        """
        with self._lock:
            if 0 <= index < len(self._entries):
                return self._entries[index]
            return None

    def get_term(self, index: int) -> int:
        """Get the term of the entry at a specific index.

        Args:
            index: Log position (0 = sentinel).

        Returns:
            The term, or 0 if index is out of range.
        """
        entry = self.get(index)
        return entry.term if entry else 0

    def get_range(self, start: int, end: int | None = None) -> list[LogEntry]:
        """Get entries in [start, end] range (inclusive).

        Args:
            start: Start index (inclusive).
            end: End index (inclusive). None = to end of log.

        Returns:
            List of log entries.
        """
        with self._lock:
            if end is None:
                return list(self._entries[start:])
            return list(self._entries[start : end + 1])

    def append(self, term: int, command_type: CommandType, payload: str) -> LogEntry:
        """Append a new entry to the log (leader only).

        The index is assigned automatically as last_index + 1.

        Args:
            term: Current Raft term.
            command_type: Type of command.
            payload: JSON-serialized command data.

        Returns:
            The newly created log entry.
        """
        with self._lock:
            index = len(self._entries)
            entry = LogEntry(
                term=term,
                index=index,
                command_type=command_type,
                payload=payload,
                timestamp=datetime.utcnow(),
            )
            self._entries.append(entry)

            logger.debug(
                "log_entry_appended",
                term=term,
                index=index,
                command=command_type,
            )

            return entry

    def append_entries(
        self, prev_log_index: int, prev_log_term: int, entries: list[LogEntry]
    ) -> bool:
        """Append entries received from the leader (AppendEntries RPC).

        Implements the Log Matching Property check and conflict resolution.

        Steps:
            1. Check that our log contains an entry at prev_log_index
               with term == prev_log_term (consistency check).
            2. If an existing entry conflicts with a new one (same index,
               different terms), delete the existing entry and all that follow.
            3. Append any new entries not already in the log.

        Args:
            prev_log_index: Index of log entry immediately preceding new entries.
            prev_log_term: Term of the entry at prev_log_index.
            entries: New entries from the leader.

        Returns:
            True if entries were accepted, False if consistency check failed.

        Reference: Ongaro & Ousterhout (2014), §5.3, Figure 2
        """
        with self._lock:
            # Step 1: Consistency check
            if prev_log_index > 0:
                if prev_log_index >= len(self._entries):
                    # We don't have an entry at prev_log_index — gap in log
                    logger.debug(
                        "log_consistency_failed",
                        prev_log_index=prev_log_index,
                        our_last_index=len(self._entries) - 1,
                        reason="missing_entry",
                    )
                    return False

                if self._entries[prev_log_index].term != prev_log_term:
                    # Entry exists but term doesn't match — log diverged
                    logger.debug(
                        "log_consistency_failed",
                        prev_log_index=prev_log_index,
                        expected_term=prev_log_term,
                        actual_term=self._entries[prev_log_index].term,
                        reason="term_mismatch",
                    )
                    return False

            # Step 2 & 3: Conflict resolution and append
            for entry in entries:
                if entry.index < len(self._entries):
                    existing = self._entries[entry.index]
                    if existing.term != entry.term:
                        # Conflict — delete this entry and all that follow
                        logger.info(
                            "log_conflict_truncation",
                            at_index=entry.index,
                            existing_term=existing.term,
                            new_term=entry.term,
                        )
                        self._entries = self._entries[: entry.index]
                        self._entries.append(entry)
                    # else: entry already exists with same term — skip (idempotent)
                else:
                    # New entry — append
                    self._entries.append(entry)

            return True

    def truncate_after(self, index: int) -> None:
        """Delete all entries after the given index.

        Used during conflict resolution when a follower's log
        diverges from the leader's.

        Args:
            index: Keep entries up to and including this index.
        """
        with self._lock:
            if index < len(self._entries) - 1:
                deleted_count = len(self._entries) - index - 1
                self._entries = self._entries[: index + 1]
                logger.info(
                    "log_truncated",
                    after_index=index,
                    entries_deleted=deleted_count,
                )

    def entries_after(self, index: int, max_count: int = 100) -> list[LogEntry]:
        """Get entries after a given index (for replication).

        Args:
            index: Start index (exclusive — entries AFTER this).
            max_count: Maximum entries to return (batch size).

        Returns:
            List of log entries after the given index.
        """
        with self._lock:
            start = index + 1
            end = min(start + max_count, len(self._entries))
            return list(self._entries[start:end])

    def is_up_to_date(self, last_log_index: int, last_log_term: int) -> bool:
        """Check if a candidate's log is at least as up-to-date as ours.

        Used in RequestVote to determine whether to grant a vote.
        Raft determines which log is more up-to-date by comparing
        the index and term of the last entries:
            - Higher term wins
            - Same term → higher index wins

        Args:
            last_log_index: Candidate's last log index.
            last_log_term: Candidate's last log term.

        Returns:
            True if the candidate's log is at least as up-to-date.

        Reference: Ongaro & Ousterhout (2014), §5.4.1
        """
        our_last_term = self.last_term
        our_last_index = self.last_index

        if last_log_term != our_last_term:
            return last_log_term > our_last_term
        return last_log_index >= our_last_index

    def get_committed_uncommitted_split(self) -> tuple[list[LogEntry], list[LogEntry]]:
        """Get committed and uncommitted entries separately.

        Returns:
            (committed_entries, uncommitted_entries) — both exclude sentinel.
        """
        with self._lock:
            committed = self._entries[1 : self._commit_index + 1]
            uncommitted = self._entries[self._commit_index + 1 :]
            return committed, uncommitted

    def __len__(self) -> int:
        """Return the number of real entries (excluding sentinel)."""
        return len(self._entries) - 1

    def __repr__(self) -> str:
        return (
            f"RaftLog(entries={len(self)}, "
            f"commit_index={self._commit_index}, "
            f"last_applied={self._last_applied}, "
            f"last_term={self.last_term})"
        )
