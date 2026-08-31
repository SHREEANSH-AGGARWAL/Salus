"""
Unit tests for Raft consensus implementation.

Tests cover:
    - RaftLog: append, consistency checks, conflict resolution, is_up_to_date
    - RaftNode: state transitions, election, vote handling, append entries
    - Safety invariants from the paper

These are fast, in-memory tests with no network I/O.
"""

from __future__ import annotations

import asyncio

import pytest

from salus.dispatch.state_machine import DispatchStateMachine
from salus.raft.log import RaftLog
from salus.raft.log_entry import CommandType, LogEntry
from salus.raft.node import NodeState, RaftNode


# ============================================================================
# RaftLog Tests
# ============================================================================


class TestRaftLog:
    """Test the replicated log implementation."""

    def test_initial_state(self) -> None:
        log = RaftLog()
        assert log.last_index == 0  # Sentinel only
        assert log.last_term == 0
        assert log.commit_index == 0
        assert len(log) == 0  # __len__ excludes sentinel

    def test_append(self) -> None:
        log = RaftLog()
        entry = log.append(term=1, command_type=CommandType.NOOP, payload="{}")
        assert entry.index == 1
        assert entry.term == 1
        assert log.last_index == 1
        assert log.last_term == 1
        assert len(log) == 1

    def test_append_multiple(self) -> None:
        log = RaftLog()
        log.append(term=1, command_type=CommandType.NOOP, payload="{}")
        log.append(term=1, command_type=CommandType.ZONE_REGISTER, payload='{"name":"Z-1"}')
        log.append(term=2, command_type=CommandType.RESOURCE_DISPATCH, payload='{"id":"r-1"}')

        assert log.last_index == 3
        assert log.last_term == 2
        assert len(log) == 3

    def test_get(self) -> None:
        log = RaftLog()
        log.append(term=1, command_type=CommandType.NOOP, payload="{}")
        entry = log.get(1)
        assert entry is not None
        assert entry.term == 1
        assert entry.index == 1

    def test_get_out_of_range(self) -> None:
        log = RaftLog()
        assert log.get(999) is None

    def test_get_term(self) -> None:
        log = RaftLog()
        log.append(term=1, command_type=CommandType.NOOP, payload="{}")
        log.append(term=2, command_type=CommandType.NOOP, payload="{}")
        assert log.get_term(0) == 0  # Sentinel
        assert log.get_term(1) == 1
        assert log.get_term(2) == 2
        assert log.get_term(99) == 0  # Out of range

    def test_commit_index_cannot_decrease(self) -> None:
        log = RaftLog()
        log.append(term=1, command_type=CommandType.NOOP, payload="{}")
        log.commit_index = 1
        with pytest.raises(ValueError):
            log.commit_index = 0

    def test_entries_after(self) -> None:
        log = RaftLog()
        for i in range(5):
            log.append(term=1, command_type=CommandType.NOOP, payload="{}")
        entries = log.entries_after(2, max_count=10)
        assert len(entries) == 3  # Indices 3, 4, 5
        assert entries[0].index == 3
        assert entries[-1].index == 5

    def test_entries_after_with_limit(self) -> None:
        log = RaftLog()
        for i in range(10):
            log.append(term=1, command_type=CommandType.NOOP, payload="{}")
        entries = log.entries_after(0, max_count=3)
        assert len(entries) == 3

    # === Log Matching Property ===

    def test_append_entries_consistency_check_passes(self) -> None:
        """Follower with matching prev_log entry accepts new entries."""
        log = RaftLog()
        log.append(term=1, command_type=CommandType.NOOP, payload="{}")

        new_entries = [
            LogEntry(term=1, index=2, command_type=CommandType.NOOP, payload="{}"),
        ]
        result = log.append_entries(prev_log_index=1, prev_log_term=1, entries=new_entries)
        assert result is True
        assert log.last_index == 2

    def test_append_entries_consistency_check_fails_missing(self) -> None:
        """Follower missing prev_log entry rejects."""
        log = RaftLog()
        # Log only has sentinel (index 0)

        new_entries = [
            LogEntry(term=1, index=5, command_type=CommandType.NOOP, payload="{}"),
        ]
        result = log.append_entries(prev_log_index=4, prev_log_term=1, entries=new_entries)
        assert result is False

    def test_append_entries_consistency_check_fails_term_mismatch(self) -> None:
        """Follower with wrong term at prev_log entry rejects."""
        log = RaftLog()
        log.append(term=1, command_type=CommandType.NOOP, payload="{}")

        new_entries = [
            LogEntry(term=2, index=2, command_type=CommandType.NOOP, payload="{}"),
        ]
        # prev_log_index=1 exists, but its term is 1, not 2
        result = log.append_entries(prev_log_index=1, prev_log_term=2, entries=new_entries)
        assert result is False

    def test_append_entries_conflict_resolution(self) -> None:
        """Conflicting entries are truncated and replaced."""
        log = RaftLog()
        log.append(term=1, command_type=CommandType.NOOP, payload="{}")
        log.append(term=1, command_type=CommandType.NOOP, payload="{}")  # Index 2, term 1

        # Leader sends entry at index 2 with term 2 (conflict)
        new_entries = [
            LogEntry(term=2, index=2, command_type=CommandType.ZONE_REGISTER, payload='{"name":"Z"}'),
        ]
        result = log.append_entries(prev_log_index=1, prev_log_term=1, entries=new_entries)
        assert result is True
        assert log.last_index == 2
        assert log.get(2).term == 2  # Replaced with new entry
        assert log.get(2).command_type == CommandType.ZONE_REGISTER

    def test_append_entries_idempotent(self) -> None:
        """Re-sending the same entries is safe (idempotent)."""
        log = RaftLog()
        log.append(term=1, command_type=CommandType.NOOP, payload="{}")

        new_entries = [
            LogEntry(term=1, index=1, command_type=CommandType.NOOP, payload="{}"),
        ]
        # Same entry at index 1, term 1 — should be a no-op
        result = log.append_entries(prev_log_index=0, prev_log_term=0, entries=new_entries)
        assert result is True
        assert log.last_index == 1

    # === Candidate Log Comparison ===

    def test_is_up_to_date_higher_term_wins(self) -> None:
        log = RaftLog()
        log.append(term=1, command_type=CommandType.NOOP, payload="{}")

        # Candidate with term 2 is more up-to-date
        assert log.is_up_to_date(last_log_index=1, last_log_term=2) is True
        # Candidate with term 0 is less up-to-date
        assert log.is_up_to_date(last_log_index=1, last_log_term=0) is False

    def test_is_up_to_date_same_term_higher_index_wins(self) -> None:
        log = RaftLog()
        log.append(term=1, command_type=CommandType.NOOP, payload="{}")

        # Same term, longer log
        assert log.is_up_to_date(last_log_index=2, last_log_term=1) is True
        # Same term, shorter log
        assert log.is_up_to_date(last_log_index=0, last_log_term=1) is False


# ============================================================================
# RaftNode Tests
# ============================================================================


class TestRaftNode:
    """Test the Raft consensus node."""

    def _make_node(
        self,
        node_id: str = "node-1",
        peers: list[str] | None = None,
    ) -> RaftNode:
        """Create a RaftNode with defaults for testing."""
        if peers is None:
            peers = ["node-2", "node-3"]
        sm = DispatchStateMachine()
        return RaftNode(
            node_id=node_id,
            peer_ids=peers,
            state_machine=sm,
            election_timeout_min_ms=150,
            election_timeout_max_ms=300,
            heartbeat_interval_ms=50,
        )

    def test_initial_state(self) -> None:
        node = self._make_node()
        assert node.state == NodeState.FOLLOWER
        assert node.current_term == 0
        assert node.voted_for is None
        assert node.leader_id is None
        assert node.cluster_size == 3
        assert node.quorum_size == 2

    def test_quorum_sizes(self) -> None:
        """Verify quorum calculation for different cluster sizes."""
        assert self._make_node(peers=["n2"]).quorum_size == 2          # 2 nodes → quorum 2
        assert self._make_node(peers=["n2", "n3"]).quorum_size == 2    # 3 → 2
        assert self._make_node(peers=["n2", "n3", "n4"]).quorum_size == 3  # 4 → 3
        assert self._make_node(peers=["n2", "n3", "n4", "n5"]).quorum_size == 3  # 5 → 3

    # === RequestVote Handler ===

    def test_vote_granted_when_not_voted(self) -> None:
        """Grant vote if we haven't voted this term and candidate's log is up-to-date."""
        node = self._make_node()
        response = node.handle_request_vote({
            "term": 1,
            "candidate_id": "node-2",
            "last_log_index": 0,
            "last_log_term": 0,
        })
        assert response["vote_granted"] is True
        assert node.voted_for == "node-2"
        assert node.current_term == 1

    def test_vote_denied_already_voted(self) -> None:
        """Deny vote if we already voted for a different candidate this term."""
        node = self._make_node()
        # Vote for node-2
        node.handle_request_vote({
            "term": 1,
            "candidate_id": "node-2",
            "last_log_index": 0,
            "last_log_term": 0,
        })
        # node-3 asks for vote in same term
        response = node.handle_request_vote({
            "term": 1,
            "candidate_id": "node-3",
            "last_log_index": 0,
            "last_log_term": 0,
        })
        assert response["vote_granted"] is False

    def test_vote_granted_same_candidate_again(self) -> None:
        """Granting vote to the same candidate again is idempotent."""
        node = self._make_node()
        node.handle_request_vote({
            "term": 1,
            "candidate_id": "node-2",
            "last_log_index": 0,
            "last_log_term": 0,
        })
        # Same candidate asks again
        response = node.handle_request_vote({
            "term": 1,
            "candidate_id": "node-2",
            "last_log_index": 0,
            "last_log_term": 0,
        })
        assert response["vote_granted"] is True

    def test_vote_denied_stale_term(self) -> None:
        """Deny vote if candidate's term < our term."""
        node = self._make_node()
        node.current_term = 5
        response = node.handle_request_vote({
            "term": 3,
            "candidate_id": "node-2",
            "last_log_index": 0,
            "last_log_term": 0,
        })
        assert response["vote_granted"] is False
        assert response["term"] == 5

    def test_vote_denied_log_not_up_to_date(self) -> None:
        """Deny vote if candidate's log is behind ours (§5.4.1)."""
        node = self._make_node()
        # Give our node a log entry at term 2
        node.log.append(term=2, command_type=CommandType.NOOP, payload="{}")

        response = node.handle_request_vote({
            "term": 3,
            "candidate_id": "node-2",
            "last_log_index": 0,
            "last_log_term": 1,  # Candidate's last term is 1, ours is 2
        })
        assert response["vote_granted"] is False

    def test_step_down_on_higher_term_vote_request(self) -> None:
        """Node steps down to follower if it sees a higher term in RequestVote."""
        node = self._make_node()
        node.current_term = 1
        node.state = NodeState.CANDIDATE

        node.handle_request_vote({
            "term": 5,
            "candidate_id": "node-2",
            "last_log_index": 0,
            "last_log_term": 0,
        })
        assert node.state == NodeState.FOLLOWER
        assert node.current_term == 5

    # === AppendEntries Handler ===

    def test_accept_heartbeat(self) -> None:
        """Follower accepts a valid heartbeat (empty AppendEntries)."""
        node = self._make_node()
        response = node.handle_append_entries({
            "term": 1,
            "leader_id": "node-2",
            "prev_log_index": 0,
            "prev_log_term": 0,
            "entries": [],
            "leader_commit": 0,
        })
        assert response["success"] is True
        assert node.leader_id == "node-2"
        assert node.current_term == 1

    def test_reject_stale_leader(self) -> None:
        """Reject AppendEntries from a leader with a stale term."""
        node = self._make_node()
        node.current_term = 5
        response = node.handle_append_entries({
            "term": 3,
            "leader_id": "node-2",
            "prev_log_index": 0,
            "prev_log_term": 0,
            "entries": [],
            "leader_commit": 0,
        })
        assert response["success"] is False
        assert response["term"] == 5

    def test_accept_entries(self) -> None:
        """Follower accepts and appends new entries."""
        node = self._make_node()
        entries = [
            {"term": 1, "index": 1, "command_type": "noop", "payload": "{}",
             "timestamp": "2026-01-01T00:00:00", "committed": False},
        ]
        response = node.handle_append_entries({
            "term": 1,
            "leader_id": "node-2",
            "prev_log_index": 0,
            "prev_log_term": 0,
            "entries": entries,
            "leader_commit": 0,
        })
        assert response["success"] is True
        assert node.log.last_index == 1

    def test_follower_advances_commit_index(self) -> None:
        """Follower advances commit index when leader_commit is higher."""
        node = self._make_node()
        # First append an entry
        entries = [
            {"term": 1, "index": 1, "command_type": "noop", "payload": "{}",
             "timestamp": "2026-01-01T00:00:00", "committed": False},
        ]
        node.handle_append_entries({
            "term": 1,
            "leader_id": "node-2",
            "prev_log_index": 0,
            "prev_log_term": 0,
            "entries": entries,
            "leader_commit": 1,  # Leader has committed this entry
        })
        assert node.log.commit_index == 1

    def test_candidate_steps_down_on_append_entries(self) -> None:
        """A candidate steps down to follower on valid AppendEntries."""
        node = self._make_node()
        node.state = NodeState.CANDIDATE
        node.current_term = 1

        response = node.handle_append_entries({
            "term": 1,
            "leader_id": "node-2",
            "prev_log_index": 0,
            "prev_log_term": 0,
            "entries": [],
            "leader_commit": 0,
        })
        assert response["success"] is True
        assert node.state == NodeState.FOLLOWER

    # === Safety Invariants ===

    def test_election_safety_one_vote_per_term(self) -> None:
        """A node can only vote once per term (Election Safety)."""
        node = self._make_node()

        # Vote for node-2 in term 1
        r1 = node.handle_request_vote({
            "term": 1, "candidate_id": "node-2",
            "last_log_index": 0, "last_log_term": 0,
        })
        assert r1["vote_granted"] is True

        # node-3 asks in same term — must be denied
        r2 = node.handle_request_vote({
            "term": 1, "candidate_id": "node-3",
            "last_log_index": 0, "last_log_term": 0,
        })
        assert r2["vote_granted"] is False

        # node-3 asks in term 2 — can vote now (new term)
        r3 = node.handle_request_vote({
            "term": 2, "candidate_id": "node-3",
            "last_log_index": 0, "last_log_term": 0,
        })
        assert r3["vote_granted"] is True
        assert node.voted_for == "node-3"

    def test_leader_completeness_reject_stale_candidate(self) -> None:
        """Nodes with committed entries reject candidates with shorter logs (§5.4.1)."""
        node = self._make_node()
        # Node has entries up to term 3
        node.log.append(term=1, command_type=CommandType.NOOP, payload="{}")
        node.log.append(term=2, command_type=CommandType.NOOP, payload="{}")
        node.log.append(term=3, command_type=CommandType.NOOP, payload="{}")

        # Candidate with shorter log in lower term
        response = node.handle_request_vote({
            "term": 4,
            "candidate_id": "node-2",
            "last_log_index": 1,
            "last_log_term": 1,
        })
        assert response["vote_granted"] is False

    # === Read-Index ===

    def test_read_index_response(self) -> None:
        """Read-index returns commit index and leader status."""
        node = self._make_node()
        node.state = NodeState.LEADER
        node.leader_id = node.node_id
        node.log.append(term=1, command_type=CommandType.NOOP, payload="{}")
        node.log.commit_index = 1

        response = node.handle_read_index({"requester_id": "node-2"})
        assert response["commit_index"] == 1
        assert response["is_leader"] is True

    # === Status ===

    def test_get_status(self) -> None:
        node = self._make_node()
        status = node.get_status()
        assert status["node_id"] == "node-1"
        assert status["state"] == "follower"
        assert status["cluster_size"] == 3
        assert status["quorum_size"] == 2
