"""
Abstract state machine interface for Raft.

This is an INTERFACE CONTRACT (C1) — defines the abstract interface
that the Raft module calls into. The dispatch state machine
(salus/dispatch/state_machine.py) implements this interface.

The Raft module is domain-agnostic: it replicates log entries and
calls apply() on the state machine. The state machine interprets
the commands and produces domain-specific state (resource availability,
zone priorities, dispatch records).

Reference: Ongaro & Ousterhout (2014), §5.3 — "each server stores
a log containing a series of commands, which its state machine
executes in order."
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from salus.raft.log_entry import LogEntry


class StateMachine(ABC):
    """Abstract state machine that the Raft consensus module drives.

    Implementations must be deterministic: given the same sequence of
    log entries, every node must produce identical state. This is the
    fundamental safety property that makes Raft work.

    Contract:
        1. apply() is called exactly once per committed log entry, in index order.
        2. apply() must be deterministic — same input → same state on all nodes.
        3. apply() must not block on external I/O.
        4. snapshot/restore must capture/rebuild the complete state.
    """

    @abstractmethod
    def apply(self, entry: LogEntry) -> Any:
        """Apply a committed log entry to the state machine.

        Called by the Raft module after an entry is committed (quorum ack).
        Must be deterministic and idempotent (safe to replay on recovery).

        Args:
            entry: The committed log entry to apply.

        Returns:
            Result of the command application (domain-specific).

        Raises:
            ValueError: If the command payload is invalid or the state
                       transition is illegal. The entry is still committed
                       but the command is rejected with an error result.
        """
        ...

    @abstractmethod
    def snapshot(self) -> bytes:
        """Create a snapshot of the current state machine state.

        Used for log compaction (§7). When the log grows too large,
        the Raft module takes a snapshot and discards old entries.
        Nodes that are far behind receive the snapshot instead of
        replaying thousands of log entries.

        Returns:
            Serialized state that can be passed to restore().
        """
        ...

    @abstractmethod
    def restore(self, data: bytes) -> None:
        """Restore state machine state from a snapshot.

        Called when a node receives a snapshot from the leader
        (InstallSnapshot RPC). Replaces all current state.

        Args:
            data: Serialized state from snapshot().
        """
        ...

    @abstractmethod
    def last_applied_index(self) -> int:
        """Return the index of the last applied log entry.

        Used by the Raft module to know where to resume applying
        entries after a restart.

        Returns:
            The log index of the last entry applied to this state machine.
            Returns 0 if no entries have been applied.
        """
        ...
