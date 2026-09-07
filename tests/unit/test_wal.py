"""
Unit tests for durable Write-Ahead Log (WAL) and crash recovery.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from salus.dispatch.state_machine import DispatchStateMachine
from salus.raft.log_entry import CommandType, LogEntry
from salus.raft.node import RaftNode
from salus.raft.wal import WALManager


@pytest.fixture
def temp_wal_dir() -> Path:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


class TestWALManager:
    """Test SQLite WAL storage operations."""

    def test_wal_meta_persistence(self, temp_wal_dir: Path) -> None:
        wal = WALManager(temp_wal_dir, node_id="test-1")
        wal.save_meta(term=5, voted_for="candidate-alpha")
        wal.close()

        # Re-open and verify
        wal2 = WALManager(temp_wal_dir, node_id="test-1")
        term, voted_for = wal2.get_meta()
        assert term == 5
        assert voted_for == "candidate-alpha"
        wal2.close()

    def test_wal_entry_append_and_recovery(self, temp_wal_dir: Path) -> None:
        wal = WALManager(temp_wal_dir, node_id="test-1")
        entries = [
            LogEntry(term=1, index=i, command_type=CommandType.NOOP, payload=f'{{"i":{i}}}')
            for i in range(1, 6)
        ]
        wal.append_entries(entries)
        wal.close()

        # Re-open and verify
        wal2 = WALManager(temp_wal_dir, node_id="test-1")
        recovered = wal2.read_all_entries()
        assert len(recovered) == 5
        assert [e.index for e in recovered] == [1, 2, 3, 4, 5]
        assert [e.payload for e in recovered] == [f'{{"i":{i}}}' for i in range(1, 6)]
        wal2.close()

    def test_wal_truncation(self, temp_wal_dir: Path) -> None:
        wal = WALManager(temp_wal_dir, node_id="test-1")
        entries = [
            LogEntry(term=1, index=i, command_type=CommandType.NOOP, payload=f'{{"i":{i}}}')
            for i in range(1, 11)
        ]
        wal.append_entries(entries)
        wal.truncate_after(5)
        wal.close()

        wal2 = WALManager(temp_wal_dir, node_id="test-1")
        recovered = wal2.read_all_entries()
        assert len(recovered) == 5
        assert [e.index for e in recovered] == [1, 2, 3, 4, 5]
        wal2.close()

    def test_wal_snapshot_compaction(self, temp_wal_dir: Path) -> None:
        wal = WALManager(temp_wal_dir, node_id="test-1")
        entries = [
            LogEntry(term=1, index=i, command_type=CommandType.NOOP, payload=f'{{"i":{i}}}')
            for i in range(1, 11)
        ]
        wal.append_entries(entries)
        wal.save_snapshot(last_index=7, last_term=1, data=b'{"snap": true}')
        wal.close()

        wal2 = WALManager(temp_wal_dir, node_id="test-1")
        snap = wal2.get_snapshot()
        assert snap is not None
        assert snap[0] == 7
        assert snap[1] == 1
        assert snap[2] == b'{"snap": true}'

        # Entries <= 7 should be compacted/deleted
        recovered = wal2.read_all_entries()
        assert [e.index for e in recovered] == [8, 9, 10]
        wal2.close()


class TestRaftCrashRecovery:
    """Test RaftNode reloading state from WAL across simulated crashes."""

    def test_node_recovers_term_and_log(self, temp_wal_dir: Path) -> None:
        sm1 = DispatchStateMachine()
        wal1 = WALManager(temp_wal_dir, node_id="node-1")
        node1 = RaftNode(
            node_id="node-1",
            peer_ids=["node-2"],
            state_machine=sm1,
            wal=wal1,
        )

        node1.current_term = 3
        node1.voted_for = "node-1"
        wal1.save_meta(node1.current_term, node1.voted_for)

        node1.log.append(term=3, command_type=CommandType.NOOP, payload='{"type":"init"}')
        node1.log.append(
            term=3, command_type=CommandType.ZONE_REGISTER, payload='{"id":"z-1","name":"Zone 1"}'
        )

        assert node1.log.last_index == 2
        wal1.close()

        # Simulate crash restart: node2 loads same WAL
        sm2 = DispatchStateMachine()
        wal2 = WALManager(temp_wal_dir, node_id="node-1")
        node2 = RaftNode(
            node_id="node-1",
            peer_ids=["node-2"],
            state_machine=sm2,
            wal=wal2,
        )

        assert node2.current_term == 3
        assert node2.voted_for == "node-1"
        assert node2.log.last_index == 2
        assert node2.log.get(2).command_type == CommandType.ZONE_REGISTER
        wal2.close()
