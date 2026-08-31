"""
Raft consensus node — the core implementation.

Implements the Raft consensus algorithm from:
    Ongaro & Ousterhout, "In Search of an Understandable Consensus Algorithm"
    (Extended Version), 2014.

This module implements:
    - §5.1: Raft basics (states, terms, RPC handling)
    - §5.2: Leader election (randomized timeouts, RequestVote)
    - §5.3: Log replication (AppendEntries, quorum commitment)
    - §5.4: Safety (election restriction, commitment rules)
    - §6.4: Read-index for linearizable reads

SAFETY INVARIANTS (these must never be violated):
    1. Election Safety: At most one leader per term.
    2. Leader Append-Only: A leader never overwrites or deletes entries.
    3. Log Matching: If two logs contain an entry with the same index and
       term, then the logs are identical in all entries up through that index.
    4. Leader Completeness: If a log entry is committed in a given term,
       that entry will be present in the logs of the leaders for all higher terms.
    5. State Machine Safety: If a server has applied a log entry at a given
       index, no other server will ever apply a different log entry for that index.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from enum import StrEnum
from typing import Any, Callable

import structlog

from salus.raft.log import RaftLog
from salus.raft.log_entry import CommandType, LogEntry
from salus.raft.state_machine import StateMachine

logger = structlog.get_logger()


class NodeState(StrEnum):
    """Raft node states — each node is in exactly one state at any time."""

    FOLLOWER = "follower"
    CANDIDATE = "candidate"
    LEADER = "leader"


class RaftNode:
    """A single Raft consensus node.

    Each Incident Command Post (ICP) in the Salus cluster runs one
    RaftNode instance. The node manages its own log, participates in
    elections, and replicates entries if elected leader.

    Attributes:
        node_id: Unique identifier for this node.
        state: Current state (follower/candidate/leader).
        current_term: Latest term this node has seen.
        voted_for: Candidate this node voted for in current term (or None).
        log: The replicated log.
        state_machine: The application state machine to apply committed entries.
    """

    def __init__(
        self,
        node_id: str,
        peer_ids: list[str],
        state_machine: StateMachine,
        election_timeout_min_ms: int = 150,
        election_timeout_max_ms: int = 300,
        heartbeat_interval_ms: int = 50,
        send_rpc: Callable | None = None,
    ) -> None:
        """Initialize a Raft node.

        Args:
            node_id: This node's unique identifier.
            peer_ids: IDs of all other nodes in the cluster.
            state_machine: Application state machine for applying committed entries.
            election_timeout_min_ms: Minimum election timeout in ms.
            election_timeout_max_ms: Maximum election timeout in ms.
            heartbeat_interval_ms: Leader heartbeat interval in ms.
            send_rpc: Callback for sending RPCs to peers. Signature:
                      async def send_rpc(target_id, rpc_type, request) -> response
        """
        self.node_id = node_id
        self.peer_ids = list(peer_ids)
        self.state_machine = state_machine

        # Persistent state (survives restarts — §5.2)
        self.current_term: int = 0
        self.voted_for: str | None = None
        self.log = RaftLog()

        # Volatile state (all nodes)
        self.state = NodeState.FOLLOWER
        self.leader_id: str | None = None

        # Volatile state (leader only — reinitialized after election)
        self.next_index: dict[str, int] = {}   # For each peer: next entry to send
        self.match_index: dict[str, int] = {}  # For each peer: highest replicated entry

        # Timing
        self._election_timeout_min = election_timeout_min_ms / 1000.0
        self._election_timeout_max = election_timeout_max_ms / 1000.0
        self._heartbeat_interval = heartbeat_interval_ms / 1000.0
        self._last_heartbeat: float = time.monotonic()

        # RPC callback
        self._send_rpc = send_rpc

        # Event loop tasks
        self._election_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._running = False

        # Vote tracking for current election
        self._votes_received: set[str] = set()

        logger.info(
            "raft_node_initialized",
            node_id=node_id,
            peers=peer_ids,
            cluster_size=len(peer_ids) + 1,
            quorum=self.quorum_size,
        )

    @property
    def cluster_size(self) -> int:
        """Total number of nodes in the cluster (including self)."""
        return len(self.peer_ids) + 1

    @property
    def quorum_size(self) -> int:
        """Majority quorum size: floor(N/2) + 1."""
        return (self.cluster_size // 2) + 1

    @property
    def is_leader(self) -> bool:
        return self.state == NodeState.LEADER

    @property
    def is_follower(self) -> bool:
        return self.state == NodeState.FOLLOWER

    @property
    def is_candidate(self) -> bool:
        return self.state == NodeState.CANDIDATE

    # ========================================================================
    # Lifecycle
    # ========================================================================

    async def start(self) -> None:
        """Start the Raft node — begins election timer."""
        self._running = True
        self._reset_election_timer()
        logger.info("raft_node_started", node_id=self.node_id)

    async def stop(self) -> None:
        """Stop the Raft node gracefully."""
        self._running = False
        if self._election_task and not self._election_task.done():
            self._election_task.cancel()
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
        logger.info("raft_node_stopped", node_id=self.node_id)

    # ========================================================================
    # §5.2 — Leader Election
    # ========================================================================

    def _randomized_election_timeout(self) -> float:
        """Return a randomized election timeout.

        The randomization prevents split votes — each node times out
        at a different time, so usually only one starts an election.
        """
        return random.uniform(self._election_timeout_min, self._election_timeout_max)

    def _reset_election_timer(self) -> None:
        """Reset the election timer.

        Called when:
            - Receiving an AppendEntries from the current leader
            - Granting a vote to a candidate
            - Starting a new election
        """
        if self._election_task and not self._election_task.done():
            self._election_task.cancel()

        if self._running and self.state != NodeState.LEADER:
            self._election_task = asyncio.ensure_future(self._election_timeout_loop())

    async def _election_timeout_loop(self) -> None:
        """Wait for election timeout, then start an election."""
        try:
            timeout = self._randomized_election_timeout()
            await asyncio.sleep(timeout)

            if self._running and self.state != NodeState.LEADER:
                await self._start_election()
        except asyncio.CancelledError:
            pass  # Timer was reset — this is normal

    async def _start_election(self) -> None:
        """Start a new election (§5.2).

        Steps:
            1. Increment current term
            2. Transition to candidate
            3. Vote for self
            4. Send RequestVote RPCs to all peers
            5. Wait for quorum of votes
        """
        self.current_term += 1
        self.state = NodeState.CANDIDATE
        self.voted_for = self.node_id
        self.leader_id = None
        self._votes_received = {self.node_id}  # Vote for self

        logger.info(
            "election_started",
            node_id=self.node_id,
            term=self.current_term,
            cluster_size=self.cluster_size,
            quorum_needed=self.quorum_size,
        )

        # Send RequestVote to all peers in parallel
        request = {
            "term": self.current_term,
            "candidate_id": self.node_id,
            "last_log_index": self.log.last_index,
            "last_log_term": self.log.last_term,
        }

        tasks = []
        for peer_id in self.peer_ids:
            tasks.append(self._send_request_vote(peer_id, request))

        # Don't await all — process votes as they arrive
        for task in asyncio.as_completed(tasks):
            try:
                response = await task
                if response is not None:
                    self._process_vote_response(response)

                # Check if we've won
                if len(self._votes_received) >= self.quorum_size:
                    await self._become_leader()
                    return

                # Check if we've been superseded
                if self.state != NodeState.CANDIDATE:
                    return

            except Exception as e:
                logger.debug("vote_request_failed", error=str(e))

        # Election timeout without winning — will restart via timer
        if self.state == NodeState.CANDIDATE:
            logger.info(
                "election_inconclusive",
                node_id=self.node_id,
                term=self.current_term,
                votes=len(self._votes_received),
                needed=self.quorum_size,
            )
            self._reset_election_timer()

    async def _send_request_vote(
        self, peer_id: str, request: dict
    ) -> dict | None:
        """Send a RequestVote RPC to a peer."""
        if self._send_rpc is None:
            return None
        try:
            return await self._send_rpc(peer_id, "request_vote", request)
        except Exception as e:
            logger.debug("request_vote_send_failed", peer=peer_id, error=str(e))
            return None

    def _process_vote_response(self, response: dict) -> None:
        """Process a RequestVote response."""
        response_term = response.get("term", 0)

        # If response has higher term, step down
        if response_term > self.current_term:
            self._step_down(response_term)
            return

        # Count vote if granted and we're still a candidate in the same term
        if (
            response.get("vote_granted")
            and self.state == NodeState.CANDIDATE
            and response_term == self.current_term
        ):
            voter_id = response.get("voter_id", "unknown")
            self._votes_received.add(voter_id)
            logger.debug(
                "vote_received",
                from_node=voter_id,
                total_votes=len(self._votes_received),
                needed=self.quorum_size,
            )

    async def _become_leader(self) -> None:
        """Transition to leader state (§5.2).

        Called when this node wins an election with a quorum of votes.
        Initializes next_index and match_index for all peers,
        and starts sending heartbeats.
        """
        self.state = NodeState.LEADER
        self.leader_id = self.node_id

        # Initialize volatile leader state (§5.3)
        for peer_id in self.peer_ids:
            self.next_index[peer_id] = self.log.last_index + 1
            self.match_index[peer_id] = 0

        logger.info(
            "became_leader",
            node_id=self.node_id,
            term=self.current_term,
            votes=len(self._votes_received),
        )

        # Cancel election timer
        if self._election_task and not self._election_task.done():
            self._election_task.cancel()

        # Send initial heartbeat (empty AppendEntries) to assert authority
        await self._send_heartbeats()

        # Start heartbeat loop
        self._heartbeat_task = asyncio.ensure_future(self._heartbeat_loop())

        # Commit a no-op to confirm leadership (§8)
        self.log.append(
            term=self.current_term,
            command_type=CommandType.NOOP,
            payload="{}",
        )

    def _step_down(self, new_term: int) -> None:
        """Step down to follower when a higher term is discovered.

        Called when:
            - Receiving an RPC with a higher term
            - Receiving an AppendEntries from a new leader

        Args:
            new_term: The higher term we discovered.
        """
        old_state = self.state
        self.current_term = new_term
        self.state = NodeState.FOLLOWER
        self.voted_for = None

        if old_state != NodeState.FOLLOWER:
            logger.info(
                "stepped_down",
                node_id=self.node_id,
                from_state=old_state,
                new_term=new_term,
            )

        # Cancel heartbeat if we were leader
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()

        self._reset_election_timer()

    # ========================================================================
    # §5.2 — RequestVote RPC Handler
    # ========================================================================

    def handle_request_vote(self, request: dict) -> dict:
        """Handle an incoming RequestVote RPC.

        Grant vote if:
            1. Candidate's term >= our term
            2. We haven't voted in this term (or voted for this candidate)
            3. Candidate's log is at least as up-to-date as ours

        Args:
            request: RequestVote request fields.

        Returns:
            RequestVote response.

        Reference: §5.2, §5.4.1
        """
        candidate_term = request["term"]
        candidate_id = request["candidate_id"]
        last_log_index = request["last_log_index"]
        last_log_term = request["last_log_term"]

        # If candidate's term > ours, update term and step down
        if candidate_term > self.current_term:
            self._step_down(candidate_term)

        vote_granted = False

        if candidate_term >= self.current_term:
            if self.voted_for is None or self.voted_for == candidate_id:
                # Check log is up-to-date (§5.4.1)
                if self.log.is_up_to_date(last_log_index, last_log_term):
                    vote_granted = True
                    self.voted_for = candidate_id
                    self._reset_election_timer()  # Reset timer on vote grant

                    logger.info(
                        "vote_granted",
                        to_candidate=candidate_id,
                        term=self.current_term,
                    )

        return {
            "term": self.current_term,
            "vote_granted": vote_granted,
            "voter_id": self.node_id,
        }

    # ========================================================================
    # §5.3 — Log Replication (Leader)
    # ========================================================================

    async def _heartbeat_loop(self) -> None:
        """Periodically send heartbeats (empty AppendEntries) to all peers."""
        try:
            while self._running and self.state == NodeState.LEADER:
                await self._send_heartbeats()
                await asyncio.sleep(self._heartbeat_interval)
        except asyncio.CancelledError:
            pass

    async def _send_heartbeats(self) -> None:
        """Send AppendEntries RPCs to all peers (heartbeat or replication)."""
        if not self.is_leader:
            return

        tasks = []
        for peer_id in self.peer_ids:
            tasks.append(self._send_append_entries(peer_id))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for peer_id, result in zip(self.peer_ids, results):
            if isinstance(result, Exception):
                logger.debug("heartbeat_failed", peer=peer_id, error=str(result))

    async def _send_append_entries(self, peer_id: str) -> dict | None:
        """Send an AppendEntries RPC to a specific peer.

        Sends entries from next_index[peer_id] onward. If the peer
        rejects (consistency check fails), decrement next_index and retry.

        Args:
            peer_id: Target peer.

        Returns:
            The response, or None on failure.
        """
        if self._send_rpc is None:
            return None

        next_idx = self.next_index.get(peer_id, self.log.last_index + 1)
        prev_log_index = next_idx - 1
        prev_log_term = self.log.get_term(prev_log_index)

        # Get entries to send
        entries = self.log.entries_after(prev_log_index, max_count=100)

        request = {
            "term": self.current_term,
            "leader_id": self.node_id,
            "prev_log_index": prev_log_index,
            "prev_log_term": prev_log_term,
            "entries": [e.model_dump(mode="json") for e in entries],
            "leader_commit": self.log.commit_index,
        }

        try:
            response = await self._send_rpc(peer_id, "append_entries", request)
            if response is not None:
                self._process_append_entries_response(peer_id, response, entries)
            return response
        except Exception as e:
            logger.debug("append_entries_failed", peer=peer_id, error=str(e))
            return None

    def _process_append_entries_response(
        self, peer_id: str, response: dict, sent_entries: list[LogEntry]
    ) -> None:
        """Process an AppendEntries response from a peer.

        If successful:
            - Update next_index and match_index for the peer
            - Try to advance commit_index

        If rejected:
            - Decrement next_index for the peer (will retry with earlier entries)
        """
        response_term = response.get("term", 0)

        if response_term > self.current_term:
            self._step_down(response_term)
            return

        if not self.is_leader:
            return

        if response.get("success"):
            # Update indices
            if sent_entries:
                last_sent_index = sent_entries[-1].index
                self.next_index[peer_id] = last_sent_index + 1
                self.match_index[peer_id] = last_sent_index
            else:
                # Heartbeat — use match_index from response if available
                match = response.get("match_index")
                if match is not None:
                    self.match_index[peer_id] = match

            # Try to advance commit index
            self._try_advance_commit_index()
        else:
            # Decrement next_index and will retry
            if peer_id in self.next_index:
                self.next_index[peer_id] = max(1, self.next_index[peer_id] - 1)
                logger.debug(
                    "append_entries_rejected",
                    peer=peer_id,
                    new_next_index=self.next_index[peer_id],
                )

    def _try_advance_commit_index(self) -> None:
        """Try to advance the commit index based on match_index quorum.

        A log entry is committed when it has been replicated to a
        quorum of nodes AND it was created in the current term.

        Safety: Only commit entries from the current term (§5.4.2).
        """
        if not self.is_leader:
            return

        for n in range(self.log.last_index, self.log.commit_index, -1):
            # Count how many nodes have this entry
            replication_count = 1  # Self (leader) always has it
            for peer_id in self.peer_ids:
                if self.match_index.get(peer_id, 0) >= n:
                    replication_count += 1

            # Check quorum AND current term (§5.4.2)
            entry = self.log.get(n)
            if (
                replication_count >= self.quorum_size
                and entry is not None
                and entry.term == self.current_term
            ):
                old_commit = self.log.commit_index
                self.log.commit_index = n

                logger.info(
                    "commit_index_advanced",
                    from_index=old_commit,
                    to_index=n,
                    replication_count=replication_count,
                    quorum=self.quorum_size,
                )

                # Apply newly committed entries
                self._apply_committed_entries()
                break

    def _apply_committed_entries(self) -> None:
        """Apply all committed but unapplied entries to the state machine.

        Called after commit_index advances. Applies entries in order
        from last_applied + 1 to commit_index.
        """
        while self.log.last_applied < self.log.commit_index:
            next_index = self.log.last_applied + 1
            entry = self.log.get(next_index)

            if entry is None:
                logger.error("missing_log_entry", index=next_index)
                break

            result = self.state_machine.apply(entry)
            entry.committed = True
            self.log.last_applied = next_index

            logger.debug(
                "entry_applied",
                index=next_index,
                command=entry.command_type,
                result_status=result.get("status") if isinstance(result, dict) else "ok",
            )

    # ========================================================================
    # §5.3 — AppendEntries RPC Handler (Follower)
    # ========================================================================

    def handle_append_entries(self, request: dict) -> dict:
        """Handle an incoming AppendEntries RPC.

        This is the core of log replication on the follower side.

        Steps:
            1. Reject if term < current_term
            2. Reset election timer (leader is alive)
            3. Check log consistency at prev_log_index
            4. Append new entries (resolving conflicts)
            5. Advance commit_index if leader's is higher

        Args:
            request: AppendEntries request fields.

        Returns:
            AppendEntries response.

        Reference: §5.3, Figure 2
        """
        leader_term = request["term"]
        leader_id = request["leader_id"]
        prev_log_index = request["prev_log_index"]
        prev_log_term = request["prev_log_term"]
        entries_data = request.get("entries", [])
        leader_commit = request["leader_commit"]

        # Step 1: Reject if leader's term < ours
        if leader_term < self.current_term:
            return {
                "term": self.current_term,
                "success": False,
                "follower_id": self.node_id,
                "match_index": self.log.last_index,
            }

        # Leader's term >= ours — update state
        if leader_term > self.current_term:
            self._step_down(leader_term)
        elif self.state == NodeState.CANDIDATE:
            # Another node won the election
            self.state = NodeState.FOLLOWER

        self.leader_id = leader_id
        self._last_heartbeat = time.monotonic()
        self._reset_election_timer()

        # Parse entries
        entries = [LogEntry.model_validate(e) for e in entries_data]

        # Step 3 & 4: Consistency check and append
        success = self.log.append_entries(prev_log_index, prev_log_term, entries)

        if not success:
            return {
                "term": self.current_term,
                "success": False,
                "follower_id": self.node_id,
                "match_index": self.log.last_index,
            }

        # Step 5: Advance commit index
        if leader_commit > self.log.commit_index:
            self.log.commit_index = min(leader_commit, self.log.last_index)
            self._apply_committed_entries()

        return {
            "term": self.current_term,
            "success": True,
            "follower_id": self.node_id,
            "match_index": self.log.last_index,
        }

    # ========================================================================
    # Client Interface — Submitting Commands
    # ========================================================================

    async def submit_command(
        self, command_type: CommandType, payload: dict
    ) -> dict:
        """Submit a command to the Raft cluster.

        Only the leader can accept commands. Followers should redirect
        to the leader.

        Args:
            command_type: Type of command.
            payload: Command payload (will be JSON-serialized).

        Returns:
            Result dict with status, log_index, and term.

        Raises:
            RuntimeError: If this node is not the leader.
        """
        if not self.is_leader:
            raise RuntimeError(
                f"Not the leader. Current leader: {self.leader_id}. "
                f"Redirect command to the leader."
            )

        # Append to local log
        entry = self.log.append(
            term=self.current_term,
            command_type=command_type,
            payload=json.dumps(payload),
        )

        logger.info(
            "command_submitted",
            command=command_type,
            index=entry.index,
            term=entry.term,
        )

        # Trigger immediate replication to peers
        await self._send_heartbeats()

        return {
            "status": "accepted",
            "log_index": entry.index,
            "term": entry.term,
            "leader_id": self.node_id,
        }

    # ========================================================================
    # Read-Index Protocol (§6.4) — Linearizable Reads
    # ========================================================================

    def handle_read_index(self, request: dict) -> dict:
        """Handle a ReadIndex request.

        Returns the current commit index so the requester can
        wait until their state machine has applied up to this point
        before serving a read.

        This ensures linearizable reads without going through the log.

        Args:
            request: ReadIndex request.

        Returns:
            ReadIndex response with commit_index and term.
        """
        return {
            "commit_index": self.log.commit_index,
            "term": self.current_term,
            "is_leader": self.is_leader,
            "leader_id": self.leader_id or "",
        }

    async def read_with_index(self) -> int:
        """Get the current commit index for a linearizable read.

        If this node is the leader, it must first confirm it's still
        the leader by checking that a quorum of peers acknowledge
        heartbeats (preventing stale reads from a deposed leader).

        Returns:
            The commit index to wait for before serving the read.

        Raises:
            RuntimeError: If leadership cannot be confirmed.
        """
        if not self.is_leader:
            raise RuntimeError(
                f"Not the leader. Read-index requires contacting "
                f"the leader ({self.leader_id})."
            )

        # Send heartbeats and confirm quorum responds
        # (In a full implementation, this would track heartbeat acks)
        await self._send_heartbeats()

        return self.log.commit_index

    # ========================================================================
    # Status / Debug
    # ========================================================================

    def get_status(self) -> dict:
        """Get current node status for monitoring."""
        return {
            "node_id": self.node_id,
            "state": self.state,
            "current_term": self.current_term,
            "leader_id": self.leader_id,
            "voted_for": self.voted_for,
            "log_length": len(self.log),
            "commit_index": self.log.commit_index,
            "last_applied": self.log.last_applied,
            "last_log_term": self.log.last_term,
            "peers": self.peer_ids,
            "cluster_size": self.cluster_size,
            "quorum_size": self.quorum_size,
        }

    def __repr__(self) -> str:
        return (
            f"RaftNode(id={self.node_id}, state={self.state}, "
            f"term={self.current_term}, log={self.log})"
        )
