"""
gRPC server implementation for Salus Raft consensus service.

Implements RaftServiceServicer to handle inter-node RPCs:
    - RequestVote (§5.2)
    - AppendEntries (§5.3)
    - ReadIndex (§6.4)
    - InstallSnapshot (§7)
    - Ping (Cluster Health)

Translates between Protobuf messages and RaftNode internal structures.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import grpc
import structlog

from salus.grpc import raft_pb2, raft_pb2_grpc

if TYPE_CHECKING:
    from salus.raft.node import RaftNode

logger = structlog.get_logger()


class RaftServiceServicer(raft_pb2_grpc.RaftServiceServicer):
    """Async gRPC servicer handling Raft RPCs on behalf of a local RaftNode."""

    def __init__(self, node: RaftNode) -> None:
        self.node = node

    async def RequestVote(
        self, request: raft_pb2.RequestVoteRequest, context: grpc.aio.ServicerContext
    ) -> raft_pb2.RequestVoteResponse:
        """Handle incoming RequestVote RPC (§5.2)."""
        req_dict = {
            "term": request.term,
            "candidate_id": request.candidate_id,
            "last_log_index": request.last_log_index,
            "last_log_term": request.last_log_term,
        }
        resp = self.node.handle_request_vote(req_dict)
        return raft_pb2.RequestVoteResponse(
            term=resp["term"],
            vote_granted=resp["vote_granted"],
            voter_id=resp["voter_id"],
        )

    async def AppendEntries(
        self, request: raft_pb2.AppendEntriesRequest, context: grpc.aio.ServicerContext
    ) -> raft_pb2.AppendEntriesResponse:
        """Handle incoming AppendEntries RPC (§5.3)."""
        entries = []
        for e in request.entries:
            payload_str = (
                e.payload.decode("utf-8")
                if isinstance(e.payload, (bytes, bytearray))
                else str(e.payload)
            )
            ts = (
                datetime.fromtimestamp(e.timestamp_unix_ms / 1000.0, tz=UTC)
                if e.timestamp_unix_ms > 0
                else datetime.now(UTC)
            )
            entries.append(
                {
                    "term": e.term,
                    "index": e.index,
                    "command_type": e.command_type,
                    "payload": payload_str,
                    "timestamp": ts,
                }
            )

        req_dict = {
            "term": request.term,
            "leader_id": request.leader_id,
            "prev_log_index": request.prev_log_index,
            "prev_log_term": request.prev_log_term,
            "entries": entries,
            "leader_commit": request.leader_commit,
        }
        resp = self.node.handle_append_entries(req_dict)
        return raft_pb2.AppendEntriesResponse(
            term=resp["term"],
            success=resp["success"],
            follower_id=resp["follower_id"],
            match_index=resp.get("match_index", 0),
        )

    async def ReadIndex(
        self, request: raft_pb2.ReadIndexRequest, context: grpc.aio.ServicerContext
    ) -> raft_pb2.ReadIndexResponse:
        """Handle incoming ReadIndex RPC (§6.4)."""
        resp = self.node.handle_read_index({"requester_id": request.requester_id})
        return raft_pb2.ReadIndexResponse(
            commit_index=resp["commit_index"],
            term=resp["term"],
            is_leader=resp["is_leader"],
            leader_id=resp.get("leader_id", ""),
        )

    async def InstallSnapshot(
        self,
        request_iterator: Any,
        context: grpc.aio.ServicerContext,
    ) -> raft_pb2.InstallSnapshotResponse:
        """Handle incoming streamed snapshot chunks (§7)."""
        total_data = bytearray()
        last_chunk = None

        async for chunk in request_iterator:
            last_chunk = chunk
            total_data.extend(chunk.data)

        if last_chunk is None:
            return raft_pb2.InstallSnapshotResponse(
                term=self.node.current_term,
                success=False,
                follower_id=self.node.node_id,
            )

        req_dict = {
            "term": last_chunk.term,
            "leader_id": last_chunk.leader_id,
            "last_included_index": last_chunk.last_included_index,
            "last_included_term": last_chunk.last_included_term,
            "data": bytes(total_data),
        }
        resp = self.node.handle_install_snapshot(req_dict)
        return raft_pb2.InstallSnapshotResponse(
            term=resp["term"],
            success=resp["success"],
            follower_id=resp["follower_id"],
        )

    async def Ping(
        self, request: raft_pb2.PingRequest, context: grpc.aio.ServicerContext
    ) -> raft_pb2.PingResponse:
        """Handle cluster health check ping."""
        status = self.node.get_status()
        state_str = str(
            status["state"].value if hasattr(status["state"], "value") else status["state"]
        )
        return raft_pb2.PingResponse(
            responder_id=self.node.node_id,
            state=state_str,
            current_term=status["current_term"],
            leader_id=status["leader_id"] or "",
            commit_index=status["commit_index"],
            last_log_index=status["log_length"],
            timestamp_unix_ms=int(time.time() * 1000),
        )


async def create_grpc_server(
    node: RaftNode,
    host: str = "0.0.0.0",
    port: int = 50051,
    max_message_size: int = 16 * 1024 * 1024,
) -> grpc.aio.Server:
    """Create and configure an async gRPC server with the RaftServiceServicer."""
    options = [
        ("grpc.max_send_message_length", max_message_size),
        ("grpc.max_receive_message_length", max_message_size),
    ]
    server = grpc.aio.server(options=options)
    servicer = RaftServiceServicer(node)
    raft_pb2_grpc.add_RaftServiceServicer_to_server(servicer, server)
    bind_addr = f"{host}:{port}"
    server.add_insecure_port(bind_addr)
    logger.info("grpc_server_configured", bind=bind_addr, node_id=node.node_id)
    return server
