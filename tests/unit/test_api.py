"""
Unit tests for Salus FastAPI REST endpoints and WebSocket broadcaster.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from salus.api.app import create_app
from salus.api.websocket import WebSocketBroadcaster
from salus.dispatch.audit import DispatchAuditLog
from salus.dispatch.commander_gate import CommanderGate
from salus.dispatch.state_machine import DispatchStateMachine
from salus.models.common import GeoLocation
from salus.models.resource import Resource, ResourceStatus, ResourceType
from salus.models.zone import AccessStatus, DamageLevel, DisasterZone, ZonePriority
from salus.raft.node import NodeState


class MockRaftNode:
    """Mock RaftNode for API testing without full network cluster."""

    def __init__(self, node_id: str = "node-1", is_leader: bool = True):
        self.node_id = node_id
        self._is_leader = is_leader
        self.current_term = 1
        self.leader_id = node_id if is_leader else "node-leader"
        self.peer_ids = ["node-2", "node-3"]
        self.cluster_size = 3
        self.quorum_size = 2
        self._is_partitioned = False
        self.commands = []

    @property
    def is_leader(self) -> bool:
        return self._is_leader

    @property
    def state(self) -> NodeState:
        return NodeState.LEADER if self._is_leader else NodeState.FOLLOWER

    @property
    def is_partitioned(self) -> bool:
        return self._is_partitioned

    def get_status(self) -> dict:
        return {
            "node_id": self.node_id,
            "state": self.state,
            "current_term": self.current_term,
            "leader_id": self.leader_id,
            "voted_for": self.node_id,
            "log_length": len(self.commands),
            "commit_index": len(self.commands),
            "last_applied": len(self.commands),
            "last_log_term": self.current_term,
            "is_partitioned": self._is_partitioned,
            "peers": self.peer_ids,
            "cluster_size": self.cluster_size,
            "quorum_size": self.quorum_size,
        }

    async def submit_command(self, command_type, payload) -> dict:
        if not self._is_leader:
            raise RuntimeError("Not the leader")
        self.commands.append((command_type, payload))
        return {
            "status": "accepted",
            "log_index": len(self.commands),
            "term": self.current_term,
        }


@pytest.fixture
def api_test_env():
    sm = DispatchStateMachine()
    # Add a sample resource
    res1 = Resource(
        id="res-1",
        name="Heavy Rescue Truck Alpha",
        callsign="RESCUE-1",
        resource_type=ResourceType.FIRE_ENGINE,
        owning_agency_id="fire_dept",
        home_base=GeoLocation(latitude=37.7749, longitude=-122.4194),
        status=ResourceStatus.AVAILABLE,
    )
    sm.resources["res-1"] = res1

    from salus.models.zone import ZoneBoundary

    zone1 = DisasterZone(
        id="zone-1",
        name="Sector 1 - Downtown",
        zone_code="Z-01",
        boundary=ZoneBoundary(
            center=GeoLocation(latitude=37.7750, longitude=-122.4190), radius_km=1.5
        ),
        priority=ZonePriority.CRITICAL,
        damage_level=DamageLevel.CATASTROPHIC,
        access_status=AccessStatus.OPEN,
    )
    sm.zones["zone-1"] = zone1

    mock_node = MockRaftNode(node_id="node-1", is_leader=True)
    gate = CommanderGate(timeout_seconds=60)
    audit = DispatchAuditLog()
    broadcaster = WebSocketBroadcaster()

    app = create_app(
        node=mock_node,
        state_machine=sm,
        gate=gate,
        audit_log=audit,
        broadcaster=broadcaster,
    )
    client = TestClient(app)

    return {
        "client": client,
        "app": app,
        "sm": sm,
        "node": mock_node,
        "gate": gate,
        "audit": audit,
        "broadcaster": broadcaster,
    }


def test_root_and_cluster_status(api_test_env):
    client = api_test_env["client"]

    # Root
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["node_id"] == "node-1"
    assert "endpoints" in data

    # Cluster status
    resp = client.get("/api/v1/cluster/status")
    assert resp.status_code == 200
    cdata = resp.json()
    assert cdata["state"] == "leader"
    assert cdata["quorum_size"] == 2

    # Health
    resp = client.get("/api/v1/cluster/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


def test_resources_availability_and_uncertain_degraded_mode(api_test_env):
    client = api_test_env["client"]
    node = api_test_env["node"]

    # Normal mode: available
    resp = client.get("/api/v1/resources")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["partitioned"] is False
    assert data["resources"][0]["status"] == "available"
    assert data["resources"][0]["is_uncertain"] is False

    # Simulate network partition
    node._is_partitioned = True

    resp = client.get("/api/v1/resources")
    assert resp.status_code == 200
    pdata = resp.json()
    assert pdata["partitioned"] is True
    assert pdata["degraded_mode"] is True
    # Non-negotiable invariant (§3.2): resources marked "uncertain"
    assert pdata["resources"][0]["status"] == "uncertain"
    assert pdata["resources"][0]["is_uncertain"] is True
    assert pdata["resources"][0]["original_status"] == "available"


def test_zones_api(api_test_env):
    client = api_test_env["client"]

    # List zones
    resp = client.get("/api/v1/zones")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["zones"][0]["name"] == "Sector 1 - Downtown"

    # Get single zone
    resp = client.get("/api/v1/zones/zone-1")
    assert resp.status_code == 200
    assert resp.json()["zone"]["id"] == "zone-1"


def test_dispatch_lifecycle_with_commander_gate(api_test_env):
    client = api_test_env["client"]
    gate = api_test_env["gate"]
    node = api_test_env["node"]

    # 1. Submit AI recommendation to IC Gate
    rec_body = {
        "dispatch_order_id": "order-101",
        "resource_id": "res-1",
        "resource_name": "Heavy Rescue Truck Alpha",
        "zone_id": "zone-1",
        "zone_name": "Sector 1",
        "incident_id": "inc-001",
        "ai_confidence": 0.92,
        "ai_reasoning": "High casualties, structural collapse requires heavy equipment",
        "alternative_resources": [],
    }
    resp = client.post("/api/v1/dispatch/recommend", json=rec_body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "queued_for_review"
    confirmation_id = data["confirmation_id"]

    # 2. Check pending queue
    resp = client.get("/api/v1/dispatch/pending")
    assert resp.status_code == 200
    pdata = resp.json()
    assert pdata["count"] == 1
    assert pdata["pending"][0]["id"] == confirmation_id

    # 3. Incident Commander confirms
    confirm_body = {
        "commander_id": "IC-Chief-Smith",
        "commander_agency_id": "fire_dept",
        "notes": "Approved for immediate deployment",
    }
    resp = client.post(f"/api/v1/dispatch/{confirmation_id}/confirm", json=confirm_body)
    assert resp.status_code == 200
    cdata = resp.json()
    assert cdata["status"] == "committed"
    assert cdata["resource_id"] == "res-1"

    # Verify Raft received command
    assert len(node.commands) == 1

    # 4. Check audit log
    resp = client.get("/api/v1/audit")
    assert resp.status_code == 200
    adata = resp.json()
    assert adata["total"] >= 2  # Match + Confirm


def test_dispatch_reject(api_test_env):
    client = api_test_env["client"]

    # Queue recommendation
    rec_body = {
        "dispatch_order_id": "order-102",
        "resource_id": "res-1",
        "zone_id": "zone-1",
        "incident_id": "inc-002",
    }
    resp = client.post("/api/v1/dispatch/recommend", json=rec_body)
    conf_id = resp.json()["confirmation_id"]

    # Reject
    reject_body = {
        "commander_id": "IC-Chief-Smith",
        "reason": "Road blocked, reassessing",
    }
    resp = client.post(f"/api/v1/dispatch/{conf_id}/reject", json=reject_body)
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"


def test_websocket_ping_pong(api_test_env):
    client = api_test_env["client"]
    with client.websocket_connect("/ws/events") as websocket:
        websocket.send_text("ping")
        data = websocket.receive_text()
        assert data == "pong"
