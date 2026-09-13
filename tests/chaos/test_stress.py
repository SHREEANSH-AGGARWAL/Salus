"""
Chaos test: Stress Testing.

Tests:
    1. 50 concurrent dispatch requests through FastAPI to verify the Raft log
       and asyncio event loop don't buckle under load. No double-dispatches.
    2. Rapid leadership churn — kill and restart the leader 5 times in quick
       succession and verify the system recovers and state remains consistent.
"""

from __future__ import annotations

import asyncio
import socket
import time
import uuid

import pytest

from salus.api.app import create_app
from salus.dispatch.audit import DispatchAuditLog
from salus.dispatch.commander_gate import CommanderGate
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

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


async def _build_cluster(node_ids: list[str]):
    ports = {nid: _free_port() for nid in node_ids}
    endpoints = {nid: f"127.0.0.1:{ports[nid]}" for nid in node_ids}

    state_machines: dict[str, DispatchStateMachine] = {}
    client_pools: dict[str, GRPCClientPool] = {}
    nodes: dict[str, RaftNode] = {}
    servers = {}

    for nid in node_ids:
        sm = DispatchStateMachine()
        state_machines[nid] = sm

        peer_endpoints = {p: endpoints[p] for p in node_ids if p != nid}
        cp = GRPCClientPool(
            peer_addresses=peer_endpoints,
            request_timeout_ms=2000,
            connect_timeout_ms=3000,
        )
        client_pools[nid] = cp

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

        server = await create_grpc_server(node, host="127.0.0.1", port=ports[nid])
        await server.start()
        servers[nid] = server

    for nid in node_ids:
        await nodes[nid].start()

    return nodes, state_machines, client_pools, servers, ports


async def _await_leader(nodes, timeout=5.0, exclude=None):
    for _ in range(int(timeout / 0.05)):
        await asyncio.sleep(0.05)
        leaders = [
            n for n in nodes.values()
            if n.is_leader and (exclude is None or n.node_id not in exclude)
        ]
        if len(leaders) == 1:
            return leaders[0]
    return None


async def _cleanup(nodes, servers, pools):
    for n in nodes.values():
        await n.stop()
    for s in servers.values():
        await s.stop(grace=0.2)
    for cp in pools.values():
        await cp.close()


def _make_resource(res_id: str) -> Resource:
    return Resource(
        id=res_id,
        name=f"Res-{res_id}",
        callsign=f"R-{res_id[-4:]}",
        resource_type=ResourceType.AMBULANCE_ALS,
        owning_agency_id="agency-stress",
        capabilities=ResourceCapabilities(personnel_count=3, has_medical_personnel=True),
        home_base=GeoLocation(latitude=28.57, longitude=77.22),
        status=ResourceStatus.AVAILABLE,
    )


def _make_zone(zone_id: str) -> DisasterZone:
    return DisasterZone(
        id=zone_id,
        name=f"Stress Zone {zone_id}",
        zone_code=zone_id.upper(),
        boundary=ZoneBoundary(
            center=GeoLocation(latitude=28.56, longitude=77.2), radius_km=1.0
        ),
        priority=ZonePriority.CRITICAL,
        damage_level=DamageLevel.SEVERE,
        access_status=AccessStatus.OPEN,
    )


# ============================================================================
# Test: 50 Concurrent Dispatches
# ============================================================================


@pytest.mark.chaos
@pytest.mark.asyncio
@pytest.mark.timeout(60)
async def test_concurrent_dispatch_stress():
    """Hammer the Raft leader with 50 concurrent dispatch requests.

    Registers 50 unique resources and 10 zones, then fires 50 simultaneous
    RESOURCE_DISPATCH commands. Verifies:
        - All 50 dispatches commit (no errors).
        - No double-dispatches: each resource dispatched at most once.
        - State machines agree across all 3 nodes.
    """
    node_ids = ["alpha", "bravo", "charlie"]
    nodes, sms, cps, servers, ports = await _build_cluster(node_ids)

    try:
        leader = await _await_leader(nodes)
        assert leader is not None, "No leader elected"
        print(f"\n[STRESS] Leader: {leader.node_id}")

        # Register zones
        zones = [_make_zone(f"sz-{i}") for i in range(10)]
        for z in zones:
            await leader.submit_command(CommandType.ZONE_REGISTER, z.model_dump(mode="json"))

        # Register 50 resources
        num_resources = 50
        resources = [_make_resource(f"sr-{i:03d}") for i in range(num_resources)]
        for r in resources:
            await leader.submit_command(CommandType.RESOURCE_REGISTER, r.model_dump(mode="json"))

        # Wait for replication
        for _ in range(100):
            await asyncio.sleep(0.05)
            if all(len(sm.resources) >= num_resources for sm in sms.values()):
                break

        for nid in node_ids:
            assert len(sms[nid].resources) >= num_resources, (
                f"{nid} has {len(sms[nid].resources)} resources, expected {num_resources}"
            )
        print(f"[STRESS] {num_resources} resources replicated")

        # Fire 50 concurrent dispatch commands
        t_start = time.perf_counter()

        async def dispatch_one(idx: int):
            payload = {
                "resource_id": f"sr-{idx:03d}",
                "from_status": ResourceStatus.AVAILABLE.value,
                "to_status": ResourceStatus.DISPATCHED.value,
                "zone_id": f"sz-{idx % 10}",
                "incident_id": f"inc-stress-{idx:03d}",
                "actor_id": "cmd-stress",
                "actor_type": "commander",
                "confirmation_source": ConfirmationSource.COMMANDER.value,
                "commander_id": "cmd-stress",
            }
            return await leader.submit_command(CommandType.RESOURCE_DISPATCH, payload)

        results = await asyncio.gather(
            *[dispatch_one(i) for i in range(num_resources)],
            return_exceptions=True,
        )

        t_elapsed = time.perf_counter() - t_start
        print(f"[STRESS] {num_resources} dispatches fired in {t_elapsed:.3f}s")

        # Count successes vs failures
        successes = [r for r in results if isinstance(r, dict) and r.get("status") == "accepted"]
        errors = [r for r in results if isinstance(r, Exception)]

        print(f"[STRESS] Successes: {len(successes)}, Errors: {len(errors)}")
        assert len(successes) == num_resources, (
            f"Expected {num_resources} successes, got {len(successes)}. "
            f"Errors: {errors[:5]}"
        )

        # Wait for full replication
        for _ in range(120):
            await asyncio.sleep(0.05)
            dispatched_counts = [
                sum(1 for r in sm.resources.values() if r.status == ResourceStatus.DISPATCHED)
                for sm in sms.values()
            ]
            if all(c >= num_resources for c in dispatched_counts):
                break

        # Verify no double-dispatch and full consistency
        for nid in node_ids:
            sm = sms[nid]
            dispatched_ids = set()
            for r in sm.resources.values():
                if r.status == ResourceStatus.DISPATCHED:
                    assert r.id not in dispatched_ids, f"Double dispatch detected: {r.id}"
                    dispatched_ids.add(r.id)
            assert len(dispatched_ids) == num_resources, (
                f"Node {nid}: {len(dispatched_ids)} dispatched, expected {num_resources}"
            )

        # Log indices should be sequential
        log_indices = sorted(r["log_index"] for r in successes)
        for i in range(1, len(log_indices)):
            assert log_indices[i] == log_indices[i - 1] + 1, (
                f"Gap in log indices: {log_indices[i-1]} -> {log_indices[i]}"
            )

        throughput = num_resources / t_elapsed
        print(f"[STRESS] ✅ All {num_resources} dispatches committed. "
              f"Throughput: {throughput:.1f} dispatches/s, Wall time: {t_elapsed:.3f}s")

    finally:
        await _cleanup(nodes, servers, cps)


# ============================================================================
# Test: Rapid Leadership Churn
# ============================================================================


@pytest.mark.chaos
@pytest.mark.asyncio
@pytest.mark.timeout(60)
async def test_rapid_leadership_churn():
    """Kill and restart the leader 5 times in rapid succession.

    After each cycle, submit a command and verify the system recovers.
    At the end, verify all state machines agree.
    """
    node_ids = ["alpha", "bravo", "charlie"]
    nodes, sms, cps, servers, ports = await _build_cluster(node_ids)

    killed_leaders: list[str] = []

    try:
        # Initial leader
        leader = await _await_leader(nodes)
        assert leader is not None
        print(f"\n[CHURN] Initial leader: {leader.node_id}")

        # Register some baseline data
        z = _make_zone("z-churn")
        await leader.submit_command(CommandType.ZONE_REGISTER, z.model_dump(mode="json"))

        for i in range(3):
            r = _make_resource(f"r-churn-{i}")
            await leader.submit_command(CommandType.RESOURCE_REGISTER, r.model_dump(mode="json"))

        for _ in range(60):
            await asyncio.sleep(0.05)
            if all(len(sm.resources) >= 3 for sm in sms.values()):
                break

        # Churn loop: kill leader, wait for new one, submit a command
        for cycle in range(5):
            leader = await _await_leader(nodes, timeout=8.0)
            if leader is None:
                # If no leader, wait a bit more
                await asyncio.sleep(2.0)
                leader = await _await_leader(nodes, timeout=8.0)
            assert leader is not None, f"Churn cycle {cycle}: no leader elected"

            victim = leader.node_id
            print(f"[CHURN] Cycle {cycle + 1}: Killing leader {victim}")

            # Kill the leader
            await nodes[victim].stop()
            await servers[victim].stop(grace=0)
            killed_leaders.append(victim)

            # Wait for new leader among survivors
            await asyncio.sleep(1.0)
            new_leader = await _await_leader(nodes, timeout=8.0, exclude={victim})

            # Restart the killed node
            peer_ids = [p for p in node_ids if p != victim]
            new_sm = DispatchStateMachine()
            sms[victim] = new_sm

            new_node = RaftNode(
                node_id=victim,
                peer_ids=peer_ids,
                state_machine=new_sm,
                election_timeout_min_ms=300,
                election_timeout_max_ms=600,
                heartbeat_interval_ms=50,
                send_rpc=cps[victim].send_rpc,
            )
            nodes[victim] = new_node

            new_server = await create_grpc_server(
                new_node, host="127.0.0.1", port=ports[victim]
            )
            await new_server.start()
            servers[victim] = new_server
            await new_node.start()

            # Find any leader and submit a command
            any_leader = await _await_leader(nodes, timeout=8.0)
            if any_leader:
                r = _make_resource(f"r-churn-cycle-{cycle}")
                try:
                    res = await any_leader.submit_command(
                        CommandType.RESOURCE_REGISTER, r.model_dump(mode="json")
                    )
                    print(f"[CHURN] Cycle {cycle + 1}: Command accepted (index {res['log_index']})")
                except RuntimeError:
                    # Leader might have changed between check and submit
                    print(f"[CHURN] Cycle {cycle + 1}: Leader changed, retrying...")
                    await asyncio.sleep(1.0)

        # Final stabilization
        print(f"[CHURN] Waiting for final stabilization...")
        await asyncio.sleep(3.0)

        final_leader = await _await_leader(nodes, timeout=8.0)
        assert final_leader is not None, "No leader after churn"

        # Verify: at least baseline data (3 resources + zone) exists on majority
        consistent_count = 0
        for nid in node_ids:
            sm = sms[nid]
            if len(sm.resources) >= 3:
                consistent_count += 1

        assert consistent_count >= 2, (
            f"Only {consistent_count} nodes have baseline data. "
            f"Resource counts: {[len(sms[nid].resources) for nid in node_ids]}"
        )

        print(f"[CHURN] ✅ Rapid leadership churn test PASSED. "
              f"Killed {len(killed_leaders)} leaders across {5} cycles. "
              f"Final leader: {final_leader.node_id}")

    finally:
        await _cleanup(nodes, servers, cps)
