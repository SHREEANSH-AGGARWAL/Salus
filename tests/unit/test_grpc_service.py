"""
Unit tests for Salus gRPC communication layer (Server & ClientPool).
"""

from __future__ import annotations

import socket

import pytest

from salus.dispatch.state_machine import DispatchStateMachine
from salus.grpc.client import GRPCClientPool
from salus.grpc.server import create_grpc_server
from salus.raft.log_entry import CommandType
from salus.raft.node import RaftNode


def get_free_port() -> int:
    """Find an available TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture
def test_node():
    sm = DispatchStateMachine()
    node = RaftNode(
        node_id="test-node-1",
        peer_ids=["test-node-2"],
        state_machine=sm,
        election_timeout_min_ms=1000,
        election_timeout_max_ms=2000,
        heartbeat_interval_ms=200,
    )
    return node


@pytest.mark.asyncio
async def test_grpc_ping_and_request_vote(test_node):
    port = get_free_port()
    server = await create_grpc_server(test_node, host="127.0.0.1", port=port)
    await server.start()

    client_pool = GRPCClientPool(
        peer_addresses={"test-node-1": f"127.0.0.1:{port}"},
        request_timeout_ms=1000,
    )

    try:
        # Test Ping
        ping_resp = await client_pool.send_rpc("test-node-1", "ping", {"sender_id": "test-node-2"})
        assert ping_resp is not None
        assert ping_resp["responder_id"] == "test-node-1"
        assert ping_resp["state"] in ("follower", "candidate", "leader")

        # Test RequestVote
        vote_req = {
            "term": 1,
            "candidate_id": "test-node-2",
            "last_log_index": 0,
            "last_log_term": 0,
        }
        vote_resp = await client_pool.send_rpc("test-node-1", "request_vote", vote_req)
        assert vote_resp is not None
        assert vote_resp["term"] == 1
        assert vote_resp["vote_granted"] is True
        assert vote_resp["voter_id"] == "test-node-1"

    finally:
        await client_pool.close()
        await server.stop(grace=0.5)


@pytest.mark.asyncio
async def test_grpc_append_entries_and_read_index(test_node):
    port = get_free_port()
    server = await create_grpc_server(test_node, host="127.0.0.1", port=port)
    await server.start()

    client_pool = GRPCClientPool(
        peer_addresses={"test-node-1": f"127.0.0.1:{port}"},
        request_timeout_ms=1000,
    )

    try:
        # Append entry
        append_req = {
            "term": 1,
            "leader_id": "test-node-2",
            "prev_log_index": 0,
            "prev_log_term": 0,
            "entries": [
                {
                    "term": 1,
                    "index": 1,
                    "command_type": CommandType.NOOP.value,
                    "payload": "{}",
                }
            ],
            "leader_commit": 1,
        }
        append_resp = await client_pool.send_rpc("test-node-1", "append_entries", append_req)
        assert append_resp is not None
        assert append_resp["success"] is True
        assert append_resp["match_index"] == 1

        # Read index
        read_resp = await client_pool.send_rpc(
            "test-node-1", "read_index", {"requester_id": "test-node-2"}
        )
        assert read_resp is not None
        assert read_resp["commit_index"] == 1
        assert read_resp["term"] == 1

    finally:
        await client_pool.close()
        await server.stop(grace=0.5)


@pytest.mark.asyncio
async def test_grpc_install_snapshot(test_node):
    port = get_free_port()
    server = await create_grpc_server(test_node, host="127.0.0.1", port=port)
    await server.start()

    client_pool = GRPCClientPool(
        peer_addresses={"test-node-1": f"127.0.0.1:{port}"},
        request_timeout_ms=1000,
        snapshot_chunk_size=10,  # Small chunk size to test multi-chunk streaming
    )

    try:
        source_sm = DispatchStateMachine()
        snapshot_data = source_sm.snapshot()
        snap_req = {
            "term": 2,
            "leader_id": "test-node-2",
            "last_included_index": 5,
            "last_included_term": 2,
            "data": snapshot_data,
        }
        snap_resp = await client_pool.send_rpc("test-node-1", "install_snapshot", snap_req)
        assert snap_resp is not None
        assert snap_resp["success"] is True
        assert snap_resp["term"] == 2
        assert test_node.log.commit_index == 5
        assert test_node.current_term == 2

    finally:
        await client_pool.close()
        await server.stop(grace=0.5)
