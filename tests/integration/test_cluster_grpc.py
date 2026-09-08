"""
Multi-node in-process integration test for Salus Raft cluster over real gRPC.

Validates:
    1. Leader election (§5.2) across 3 ICP nodes over async gRPC channels.
    2. Log replication (§5.3) and commit quorum (2/3 nodes).
    3. Replicated state machine consistency (§5.4) across all nodes.
"""

from __future__ import annotations

import asyncio
import socket

import pytest

from salus.dispatch.state_machine import DispatchStateMachine
from salus.models.common import GeoLocation
from salus.models.resource import Resource, ResourceStatus, ResourceType
from salus.models.zone import AccessStatus, DamageLevel, DisasterZone, ZoneBoundary, ZonePriority
from salus.raft.log_entry import CommandType
from salus.raft.node import RaftNode
from salus.transport.client import GRPCClientPool
from salus.transport.server import create_grpc_server


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.mark.asyncio
async def test_three_node_raft_grpc_cluster():
    node_ids = ["alpha", "bravo", "charlie"]
    ports = {nid: get_free_port() for nid in node_ids}
    endpoints = {nid: f"127.0.0.1:{ports[nid]}" for nid in node_ids}

    state_machines: dict[str, DispatchStateMachine] = {}
    client_pools: dict[str, GRPCClientPool] = {}
    nodes: dict[str, RaftNode] = {}
    servers = {}

    try:
        # 1. Initialize nodes and gRPC servers
        for nid in node_ids:
            sm = DispatchStateMachine()
            state_machines[nid] = sm

            # Client pool for peers
            peer_endpoints = {p: endpoints[p] for p in node_ids if p != nid}
            cp = GRPCClientPool(
                peer_addresses=peer_endpoints,
                request_timeout_ms=1000,
                connect_timeout_ms=2000,
            )
            client_pools[nid] = cp

            # Raft node with short election timeouts
            peer_ids = [p for p in node_ids if p != nid]
            node = RaftNode(
                node_id=nid,
                peer_ids=peer_ids,
                state_machine=sm,
                election_timeout_min_ms=300,
                election_timeout_max_ms=600,
                heartbeat_interval_ms=50,
                send_rpc=cp.send_rpc,
            )
            nodes[nid] = node

            # gRPC server
            server = await create_grpc_server(node, host="127.0.0.1", port=ports[nid])
            await server.start()
            servers[nid] = server

        # 2. Start Raft election timers
        for nid in node_ids:
            await nodes[nid].start()

        # 3. Wait for leader election (max 3 seconds)
        leader: RaftNode | None = None
        for _ in range(60):
            await asyncio.sleep(0.05)
            leaders = [n for n in nodes.values() if n.is_leader]
            if len(leaders) == 1:
                leader = leaders[0]
                break

        assert leader is not None, "A leader was not elected within the timeout"
        assert leader.current_term >= 1
        print(f"\nElected leader: {leader.node_id} (term: {leader.current_term})")

        # 4. Submit ZONE_REGISTER to the elected leader
        test_zone = DisasterZone(
            id="zone-integration-1",
            name="Sector 5 - Hospital Area",
            zone_code="Z-05",
            boundary=ZoneBoundary(
                center=GeoLocation(latitude=37.7800, longitude=-122.4100), radius_km=1.0
            ),
            priority=ZonePriority.CRITICAL,
            damage_level=DamageLevel.SEVERE,
            access_status=AccessStatus.OPEN,
        )

        res = await leader.submit_command(
            CommandType.ZONE_REGISTER,
            test_zone.model_dump(mode="json"),
        )
        assert res["status"] == "accepted"

        # 5. Wait for replication across all nodes
        for _ in range(40):
            await asyncio.sleep(0.05)
            # Check if all 3 state machines have applied the zone
            if all("zone-integration-1" in sm.zones for sm in state_machines.values()):
                break

        for nid, sm in state_machines.items():
            assert "zone-integration-1" in sm.zones, (
                f"Node {nid} did not replicate zone-integration-1"
            )
            assert sm.zones["zone-integration-1"].name == "Sector 5 - Hospital Area"

        # 6. Submit RESOURCE_REGISTER to leader
        test_res = Resource(
            id="res-integration-1",
            name="Helicopter Med-1",
            callsign="MED-1",
            resource_type=ResourceType.HELICOPTER_MEDICAL,
            owning_agency_id="ems_air",
            home_base=GeoLocation(latitude=37.7800, longitude=-122.4100),
            status=ResourceStatus.AVAILABLE,
        )

        res = await leader.submit_command(
            CommandType.RESOURCE_REGISTER,
            test_res.model_dump(mode="json"),
        )
        assert res["status"] == "accepted"

        # Wait for resource replication
        for _ in range(40):
            await asyncio.sleep(0.05)
            if all("res-integration-1" in sm.resources for sm in state_machines.values()):
                break

        for nid, sm in state_machines.items():
            assert "res-integration-1" in sm.resources, (
                f"Node {nid} did not replicate res-integration-1"
            )
            assert sm.resources["res-integration-1"].status == ResourceStatus.AVAILABLE

    finally:
        # Cleanup
        for n in nodes.values():
            await n.stop()
        for s in servers.values():
            await s.stop(grace=0.2)
        for cp in client_pools.values():
            await cp.close()
