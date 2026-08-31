"""
Agency data model.

Represents a responding agency (Fire Department, EMS, Military, NDRF, NGO)
and its associated Incident Command Post (ICP) which runs a Raft node.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from salus.models.common import GeoLocation


class AgencyType(StrEnum):
    """Types of disaster response agencies."""

    FIRE_DEPARTMENT = "fire_department"
    EMS = "ems"                          # Emergency Medical Services
    POLICE = "police"
    MILITARY = "military"
    NDRF = "ndrf"                        # National Disaster Response Force
    SDRF = "sdrf"                        # State Disaster Response Force
    COAST_GUARD = "coast_guard"
    RED_CROSS = "red_cross"
    NGO = "ngo"
    GOVERNMENT = "government"            # Municipal/state emergency management
    UTILITY = "utility"                  # Power, water, telecom companies


class ICPStatus(StrEnum):
    """Incident Command Post operational status."""

    OPERATIONAL = "operational"          # Fully operational, connected to cluster
    DEGRADED = "degraded"               # Operating but with connectivity issues
    PARTITIONED = "partitioned"         # Network partitioned from majority — read-only mode
    OFFLINE = "offline"                  # ICP is offline/unreachable
    DEPLOYING = "deploying"              # ICP being set up, not yet operational


class Agency(BaseModel):
    """A responding agency and its Incident Command Post.

    Each agency operates an ICP — a physical command post (mobile trailer,
    tent, or building) from which the Incident Commander coordinates
    that agency's resources. Each ICP runs a Raft node in the Salus cluster.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique agency ID")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Identity
    name: str = Field(..., min_length=1, description="Agency name (e.g., 'NDRF Battalion 1')")
    code: str = Field(..., min_length=1, max_length=10, description="Short code (e.g., 'NDRF-1')")
    agency_type: AgencyType = Field(..., description="Type of agency")

    # Command
    incident_commander: str | None = Field(
        None, description="Name of the agency's Incident Commander"
    )
    commander_contact: str | None = Field(
        None, description="Commander's contact (radio channel, sat phone)"
    )

    # ICP (Incident Command Post)
    icp_location: GeoLocation | None = Field(None, description="ICP physical location")
    icp_status: ICPStatus = Field(ICPStatus.DEPLOYING, description="ICP operational status")

    # Resources owned
    resource_ids: list[str] = Field(
        default_factory=list,
        description="Resources owned by this agency",
    )
    total_resources: int = Field(0, ge=0, description="Total resource count")
    available_resources: int = Field(0, ge=0, description="Currently available resources")

    # Raft cluster membership
    raft_node_id: str | None = Field(None, description="Raft node ID for this ICP")
    grpc_address: str | None = Field(None, description="gRPC endpoint (host:port)")
    api_address: str | None = Field(None, description="REST API endpoint (host:port)")

    # Connectivity
    connectivity_type: str = Field(
        "lan", description="Primary connectivity: 'lan', 'satellite', 'mesh_radio', 'cellular'"
    )
    last_heartbeat_at: datetime | None = Field(
        None, description="Last successful Raft heartbeat from this ICP"
    )

    model_config = {"json_schema_extra": {"examples": [
        {
            "name": "NDRF 1st Battalion",
            "code": "NDRF-1",
            "agency_type": "ndrf",
            "incident_commander": "Cmdr. Vikram Singh",
            "commander_contact": "SAT-CH-7",
            "icp_location": {"latitude": 28.5500, "longitude": 77.2000},
            "icp_status": "operational",
            "connectivity_type": "satellite",
        }
    ]}}
