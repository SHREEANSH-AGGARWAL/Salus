"""
gRPC client pool for Salus Raft consensus cluster communication.

Manages persistent gRPC client stubs to peer ICP nodes with:
    - Connection reuse and channel pooling
    - Automatic serialization from domain dicts to Protobuf messages
    - Per-RPC timeout enforcement
    - Graceful error handling (network disconnects, timeouts)
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

import grpc
import structlog

from salus.grpc import raft_pb2, raft_pb2_grpc

if TYPE_CHECKING:
    from salus.config import ClusterPeer

logger = structlog.get_logger()


class GRPCClientPool:
    """Connection pool managing async gRPC channels and stubs to Raft cluster peers."""

    def __init__(
        self,
        peer_addresses: dict[str, str] | list[ClusterPeer],
        request_timeout_ms: int = 2000,
        connect_timeout_ms: int = 5000,
        max_message_size: int = 16 * 1024 * 1024,
        snapshot_chunk_size: int = 64 * 1024,
    ) -> None:
        """Initialize the client pool.

        Args:
            peer_addresses: Map of node_id -> "host:port", or list of ClusterPeer configs.
            request_timeout_ms: Per-RPC timeout in milliseconds.
            connect_timeout_ms: Connection timeout in milliseconds.
            max_message_size: Maximum gRPC message size in bytes.
            snapshot_chunk_size: Chunk size for InstallSnapshot streaming in bytes.
        """
        self._endpoints: dict[str, str] = {}
        if isinstance(peer_addresses, list):
            for peer in peer_addresses:
                self._endpoints[peer.node_id] = peer.grpc_address
        else:
            self._endpoints = dict(peer_addresses)

        self.request_timeout = request_timeout_ms / 1000.0
        self.connect_timeout = connect_timeout_ms / 1000.0
        self.max_message_size = max_message_size
        self.snapshot_chunk_size = snapshot_chunk_size

        self._channels: dict[str, grpc.aio.Channel] = {}
        self._stubs: dict[str, raft_pb2_grpc.RaftServiceStub] = {}
        self._lock = asyncio.Lock()

    def add_peer(self, node_id: str, address: str) -> None:
        """Register or update an endpoint for a peer."""
        self._endpoints[node_id] = address

    async def get_stub(self, peer_id: str) -> raft_pb2_grpc.RaftServiceStub | None:
        """Get or create an active gRPC stub for a peer node."""
        if peer_id not in self._endpoints:
            return None

        async with self._lock:
            if peer_id in self._stubs:
                return self._stubs[peer_id]

            target = self._endpoints[peer_id]
            options = [
                ("grpc.max_send_message_length", self.max_message_size),
                ("grpc.max_receive_message_length", self.max_message_size),
            ]
            channel = grpc.aio.insecure_channel(target, options=options)
            stub = raft_pb2_grpc.RaftServiceStub(channel)
            self._channels[peer_id] = channel
            self._stubs[peer_id] = stub
            return stub

    async def send_rpc(
        self, peer_id: str, rpc_type: str, request: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Dispatch a Raft RPC to a peer node.

        Matches the signature expected by RaftNode._send_rpc:
            Callable[[str, str, dict], Coroutine[Any, Any, dict]]

        Args:
            peer_id: Target peer identifier.
            rpc_type: RPC method ('request_vote', 'append_entries', 'read_index',
                                   'install_snapshot', 'ping').
            request: RPC payload dictionary.

        Returns:
            Dictionary response from peer, or None if RPC fails / times out.
        """
        stub = await self.get_stub(peer_id)
        if stub is None:
            logger.debug("peer_endpoint_unknown", peer_id=peer_id)
            return None

        try:
            if rpc_type == "request_vote":
                return await self._send_request_vote(stub, request)
            elif rpc_type == "append_entries":
                return await self._send_append_entries(stub, request)
            elif rpc_type == "read_index":
                return await self._send_read_index(stub, request)
            elif rpc_type == "install_snapshot":
                return await self._send_install_snapshot(stub, request)
            elif rpc_type == "ping":
                return await self._send_ping(stub, request)
            else:
                logger.error("unknown_rpc_type", rpc_type=rpc_type)
                return None
        except grpc.aio.AioRpcError as e:
            logger.debug(
                "grpc_rpc_failed",
                peer_id=peer_id,
                rpc_type=rpc_type,
                code=e.code().name if hasattr(e.code(), "name") else str(e.code()),
                details=e.details(),
            )
            return None
        except TimeoutError:
            logger.debug("grpc_rpc_timeout", peer_id=peer_id, rpc_type=rpc_type)
            return None
        except Exception as e:
            logger.debug("grpc_rpc_error", peer_id=peer_id, rpc_type=rpc_type, error=str(e))
            return None

    # ========================================================================
    # RPC Type Handlers
    # ========================================================================

    async def _send_request_vote(
        self, stub: raft_pb2_grpc.RaftServiceStub, request: dict[str, Any]
    ) -> dict[str, Any]:
        proto_req = raft_pb2.RequestVoteRequest(
            term=request["term"],
            candidate_id=request["candidate_id"],
            last_log_index=request["last_log_index"],
            last_log_term=request["last_log_term"],
        )
        resp = await stub.RequestVote(proto_req, timeout=self.request_timeout)
        return {
            "term": resp.term,
            "vote_granted": resp.vote_granted,
            "voter_id": resp.voter_id,
        }

    async def _send_append_entries(
        self, stub: raft_pb2_grpc.RaftServiceStub, request: dict[str, Any]
    ) -> dict[str, Any]:
        proto_entries = []
        for e in request.get("entries", []):
            payload_bytes = (
                e["payload"].encode("utf-8") if isinstance(e["payload"], str) else e["payload"]
            )
            ts_ms = 0
            ts = e.get("timestamp")
            if isinstance(ts, datetime):
                ts_ms = int(ts.timestamp() * 1000)
            elif isinstance(ts, (int, float)):
                ts_ms = int(ts * 1000)

            proto_entries.append(
                raft_pb2.RaftLogEntry(
                    term=e["term"],
                    index=e["index"],
                    command_type=str(e["command_type"]),
                    payload=payload_bytes,
                    timestamp_unix_ms=ts_ms,
                )
            )

        proto_req = raft_pb2.AppendEntriesRequest(
            term=request["term"],
            leader_id=request["leader_id"],
            prev_log_index=request["prev_log_index"],
            prev_log_term=request["prev_log_term"],
            entries=proto_entries,
            leader_commit=request["leader_commit"],
        )
        resp = await stub.AppendEntries(proto_req, timeout=self.request_timeout)
        return {
            "term": resp.term,
            "success": resp.success,
            "follower_id": resp.follower_id,
            "match_index": resp.match_index,
        }

    async def _send_read_index(
        self, stub: raft_pb2_grpc.RaftServiceStub, request: dict[str, Any]
    ) -> dict[str, Any]:
        proto_req = raft_pb2.ReadIndexRequest(requester_id=request.get("requester_id", ""))
        resp = await stub.ReadIndex(proto_req, timeout=self.request_timeout)
        return {
            "commit_index": resp.commit_index,
            "term": resp.term,
            "is_leader": resp.is_leader,
            "leader_id": resp.leader_id,
        }

    async def _send_install_snapshot(
        self, stub: raft_pb2_grpc.RaftServiceStub, request: dict[str, Any]
    ) -> dict[str, Any]:
        data: bytes = request["data"]
        term = request["term"]
        leader_id = request["leader_id"]
        last_index = request["last_included_index"]
        last_term = request["last_included_term"]
        chunk_size = self.snapshot_chunk_size

        async def chunk_generator():
            total_len = len(data)
            offset = 0
            if total_len == 0:
                yield raft_pb2.SnapshotChunk(
                    term=term,
                    leader_id=leader_id,
                    last_included_index=last_index,
                    last_included_term=last_term,
                    offset=0,
                    data=b"",
                    done=True,
                )
                return

            while offset < total_len:
                chunk = data[offset : offset + chunk_size]
                offset += len(chunk)
                done = offset >= total_len
                yield raft_pb2.SnapshotChunk(
                    term=term,
                    leader_id=leader_id,
                    last_included_index=last_index,
                    last_included_term=last_term,
                    offset=offset - len(chunk),
                    data=chunk,
                    done=done,
                )

        resp = await stub.InstallSnapshot(chunk_generator(), timeout=self.request_timeout * 3)
        return {
            "term": resp.term,
            "success": resp.success,
            "follower_id": resp.follower_id,
        }

    async def _send_ping(
        self, stub: raft_pb2_grpc.RaftServiceStub, request: dict[str, Any]
    ) -> dict[str, Any]:
        proto_req = raft_pb2.PingRequest(
            sender_id=request.get("sender_id", ""),
            timestamp_unix_ms=int(time.time() * 1000),
        )
        resp = await stub.Ping(proto_req, timeout=self.request_timeout)
        return {
            "responder_id": resp.responder_id,
            "state": resp.state,
            "current_term": resp.current_term,
            "leader_id": resp.leader_id,
            "commit_index": resp.commit_index,
            "last_log_index": resp.last_log_index,
            "timestamp_unix_ms": resp.timestamp_unix_ms,
        }

    async def close(self) -> None:
        """Close all active channels."""
        async with self._lock:
            for peer_id, channel in list(self._channels.items()):
                try:
                    await channel.close()
                except Exception as e:
                    logger.debug("channel_close_failed", peer_id=peer_id, error=str(e))
            self._channels.clear()
            self._stubs.clear()
