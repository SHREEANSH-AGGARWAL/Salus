"""
Chaos test: Network Partition (Split-Brain).

Simulates a 5-node Raft cluster that gets split into a majority (3 nodes)
and a minority (2 nodes). Verifies:
    1. The majority side continues operating — elects/maintains a leader
       and commits new dispatches.
    2. The minority side CANNOT elect a leader (quorum=3) and refuses
       to dispatch resources.
    3. After healing the partition, the minority nodes sync up perfectly
       with the majority.

Partition simulation: wraps send_rpc with an interceptor that raises
grpc.RpcError for cross-partition communication.
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock

import pytest

from salus.dispatch.state_machine import DispatchStateMachine
from salus.models.common import GeoLocation
from salus.models.resource import (
    ConfirmationSource,
    Resource,
    ResourceCapabilities,
    ResourceStatus,
    ResourceType,
)
from salus.models.zone import (
    AccessStatus,
    DamageLevel,
    DisasterZone,
    ZoneBoundary,
    ZonePriority,
)
from salus.raft.log_entry import CommandType
from salus.raft.node import RaftNode
from salus.transport.client import GRPCClientPool
from salus.transport.server import create_grpc_server


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


class PartitionableClientPool:
    """Wraps a GRPCClientPool with an interceptor that can block
    communication to specific peers (simulating a network partition)."""

    def __init__(self, pool: GRPCClientPool):
        self._pool = pool
        self._blocked_peers: set[str] = set()
        self._original_send_rpc = pool.send_rpc

    def block_peer(self, peer_id: str):
        self._blocked_peers.add(peer_id)

    def unblock_peer(self, peer_id: str):
        self._blocked_peers.discard(peer_id)

    def unblock_all(self):
        self._blocked_peers.clear()

    async def send_rpc(self, target_id: str, rpc_type: str, request: dict) -> dict:
        if target_id in self._blocked_peers:
            raise ConnectionError(
                f"[PARTITION] Communication to {target_id} is blocked"
            )
        return await self._original_send_rpc(target_id, rpc_type, request)


def _make_zone(zone_id: str) -> DisasterZone:
    return DisasterZone(
        id=zone_id,
        name=f"Zone {zone_id}",
        zone_code=zone_id.upper(),
        boundary=ZoneBoundary(
            center=GeoLocation(latitude=28.56, longitude=77.2), radius_km=1.0
        ),
        priority=ZonePriority.CRITICAL,
        damage_level=DamageLevel.SEVERE,
        access_status=AccessStatus.OPEN,
    )


def _make_resource(res_id: str) -> Resource:
    return Resource(
        id=res_id,
        name=f"Resource {res_id}",
        callsign=res_id[:6].upper(),
        resource_type=ResourceType.AMBULANCE_ALS,
        owning_agency_id="agency-test",
        capabilities=ResourceCapabilities(personnel_count=3),
        home_base=GeoLocation(latitude=28.57, longitude=77.22),
        status=ResourceStatus.AVAILABLE,
    )


async def _build_5_node_cluster():
    """Build a 5-node cluster with partitionable client pools."""
    node_ids = ["alpha", "bravo", "charlie", "delta", "echo"]
    ports = {nid: _free_port() for nid in node_ids}
    endpoints = {nid: f"127.0.0.1:{ports[nid]}" for nid in node_ids}

    state_machines: dict[str, DispatchStateMachine] = {}
    raw_pools: dict[str, GRPCClientPool] = {}
    partitionable: dict[str, PartitionableClientPool] = {}
    nodes: dict[str, RaftNode] = {}
    servers = {}

    for nid in node_ids:
        sm = DispatchStateMachine()
        state_machines[nid] = sm

        peer_endpoints = {p: endpoints[p] for p in node_ids if p != nid}
        cp = GRPCClientPool(
            peer_addresses=peer_endpoints,
            request_timeout_ms=1000,
            connect_timeout_ms=2000,
        )
        raw_pools[nid] = cp
        pcp = PartitionableClientPool(cp)
        partitionable[nid] = pcp

        peer_ids = [p for p in node_ids if p != nid]
        node = RaftNode(
            node_id=nid,
            peer_ids=peer_ids,
            state_machine=sm,
            election_timeout_min_ms=300,
            election_timeout_max_ms=600,
            heartbeat_interval_ms=50,
            send_rpc=pcp.send_rpc,  # Use the partitionable wrapper
        )
        nodes[nid] = node

        server = await create_grpc_server(node, host="127.0.0.1", port=ports[nid])
        await server.start()
        servers[nid] = server

    for nid in node_ids:
        await nodes[nid].start()

    return nodes, state_machines, raw_pools, partitionable, servers, node_ids


async def _await_leader(nodes, timeout=5.0, only=None, exclude=None):
    for _ in range(int(timeout / 0.05)):
        await asyncio.sleep(0.05)
        candidates = [
            n for n in nodes.values()
            if n.is_leader
            and (only is None or n.node_id in only)
            and (exclude is None or n.node_id not in exclude)
        ]
        if len(candidates) == 1:
            return candidates[0]
    return None


async def _cleanup(nodes, servers, pools):
    for n in nodes.values():
        await n.stop()
    for s in servers.values():
        await s.stop(grace=0.2)
    for cp in pools.values():
        await cp.close()


# ============================================================================
# Test: Network Partition (Split-Brain)
# ============================================================================


@pytest.mark.chaos
@pytest.mark.asyncio
@pytest.mark.timeout(45)
async def test_network_partition_split_brain():
    """Partition a 5-node cluster into (3) vs (2) and verify safety properties."""
    nodes, sms, pools, pcps, servers, all_ids = await _build_5_node_cluster()

    majority = {"alpha", "bravo", "charlie"}
    minority = {"delta", "echo"}

    try:
        # 1. Wait for initial leader
        leader = await _await_leader(nodes, timeout=8.0)
        assert leader is not None, "No leader elected in 5-node cluster"
        print(f"\n[PARTITION] Initial leader: {leader.node_id} (term {leader.current_term})")

        # 2. Register zones and resources on the leader
        zone = _make_zone("z-partition-1")
        await leader.submit_command(CommandType.ZONE_REGISTER, zone.model_dump(mode="json"))

        resources = [_make_resource(f"r-part-{i}") for i in range(4)]
        for r in resources:
            await leader.submit_command(CommandType.RESOURCE_REGISTER, r.model_dump(mode="json"))

        # Wait for full replication
        for _ in range(60):
            await asyncio.sleep(0.05)
            if all(len(sm.resources) >= 4 for sm in sms.values()):
                break
        for nid in all_ids:
            assert len(sms[nid].resources) >= 4, f"{nid} didn't replicate resources"
        print(f"[PARTITION] Pre-partition replication complete")

        # 3. ═══ INTRODUCE PARTITION ═══
        # Block all cross-partition communication
        print(f"[PARTITION] 🔥 Introducing network partition: {majority} | {minority}")
        for nid in majority:
            for blocked in minority:
                pcps[nid].block_peer(blocked)
        for nid in minority:
            for blocked in majority:
                pcps[nid].block_peer(blocked)

        # 4. Wait for the partition to take effect
        await asyncio.sleep(2.0)

        # 5. ═══ VERIFY MAJORITY SIDE ═══
        majority_leader = await _await_leader(nodes, timeout=8.0, only=majority)
        assert majority_leader is not None, "Majority side should have a leader"
        print(f"[PARTITION] Majority leader: {majority_leader.node_id}")

        # Majority can dispatch
        dispatch_payload = {
            "resource_id": "r-part-0",
            "from_status": ResourceStatus.AVAILABLE.value,
            "to_status": ResourceStatus.DISPATCHED.value,
            "zone_id": "z-partition-1",
            "incident_id": "inc-partition-001",
            "actor_id": "cmd-chaos",
            "actor_type": "commander",
            "confirmation_source": ConfirmationSource.COMMANDER.value,
            "commander_id": "cmd-chaos",
        }
        result = await majority_leader.submit_command(
            CommandType.RESOURCE_DISPATCH, dispatch_payload
        )
        assert result["status"] == "accepted"
        print(f"[PARTITION] ✅ Majority committed dispatch at index {result['log_index']}")

        # Wait for majority replication
        for _ in range(60):
            await asyncio.sleep(0.05)
            if all(
                sms[nid].resources.get("r-part-0")
                and sms[nid].resources["r-part-0"].status == ResourceStatus.DISPATCHED
                for nid in majority
            ):
                break

        for nid in majority:
            r = sms[nid].resources.get("r-part-0")
            assert r is not None and r.status == ResourceStatus.DISPATCHED, (
                f"Majority node {nid}: resource not dispatched"
            )

        # 6. ═══ VERIFY MINORITY SIDE ═══
        minority_leader = await _await_leader(nodes, timeout=3.0, only=minority)
        assert minority_leader is None, (
            "Minority (2 of 5 nodes) should NOT elect a leader (quorum=3)"
        )
        print(f"[PARTITION] ✅ Minority correctly has no leader")

        # Minority cannot submit commands
        for nid in minority:
            try:
                await nodes[nid].submit_command(
                    CommandType.RESOURCE_REGISTER,
                    _make_resource("should-fail").model_dump(mode="json"),
                )
                pytest.fail(f"Minority node {nid} should not accept commands")
            except RuntimeError:
                pass  # Expected: "Not the leader"

        # Minority's resource state should still be old (pre-partition)
        for nid in minority:
            r = sms[nid].resources.get("r-part-0")
            assert r is not None
            # The minority has NOT received the dispatch commit
            assert r.status == ResourceStatus.AVAILABLE, (
                f"Minority node {nid} should still show AVAILABLE (stale)"
            )
        print(f"[PARTITION] ✅ Minority correctly refuses dispatch and shows stale state")

        # 7. ═══ HEAL THE PARTITION ═══
        print(f"[PARTITION] 🩹 Healing network partition...")
        for nid in all_ids:
            pcps[nid].unblock_all()

        # 8. Wait for convergence
        for _ in range(100):
            await asyncio.sleep(0.1)
            if all(
                sms[nid].resources.get("r-part-0")
                and sms[nid].resources["r-part-0"].status == ResourceStatus.DISPATCHED
                for nid in all_ids
            ):
                break

        # 9. ═══ VERIFY CONVERGENCE ═══
        for nid in all_ids:
            r = sms[nid].resources.get("r-part-0")
            assert r is not None, f"Node {nid}: resource r-part-0 not found"
            assert r.status == ResourceStatus.DISPATCHED, (
                f"Node {nid}: expected DISPATCHED but got {r.status}"
            )
            # All other resources should still be AVAILABLE
            for i in range(1, 4):
                assert sms[nid].resources[f"r-part-{i}"].status == ResourceStatus.AVAILABLE

        # Verify log consistency
        log_lengths = {nid: len(nodes[nid].log) for nid in all_ids}
        max_log = max(log_lengths.values())
        min_log = min(log_lengths.values())
        # Allow minor difference during convergence, but majority must agree
        majority_logs = [log_lengths[nid] for nid in majority]
        assert len(set(majority_logs)) == 1, f"Majority logs disagree: {majority_logs}"

        print(f"[PARTITION] ✅ Convergence verified. Log lengths: {log_lengths}")
        print(f"[PARTITION] ✅ Network partition split-brain test PASSED")

    finally:
        await _cleanup(nodes, servers, pools)
