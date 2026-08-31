"""
Dispatch state machine — concrete implementation of the Raft StateMachine
for disaster response resource coordination.

This is the domain-specific state machine that the Raft consensus module
drives. It maintains the authoritative state of all resources, zones,
incidents, and dispatch orders. Every state mutation is a committed
Raft log entry, guaranteeing consistency across all ICPs.

Determinism contract: Given the same sequence of log entries, every
ICP node produces IDENTICAL state. No randomness, no wall-clock reads,
no external I/O in apply().
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from salus.models.dispatch import DispatchOrder, DispatchStatus
from salus.models.incident import Incident, IncidentStatus
from salus.models.resource import (
    ConfirmationSource,
    Resource,
    ResourceStatus,
    ResourceStateTransition,
    is_valid_transition,
)
from salus.models.zone import DisasterZone, ZonePriority
from salus.raft.log_entry import CommandType, LogEntry
from salus.raft.state_machine import StateMachine

logger = structlog.get_logger()


class DispatchStateMachine(StateMachine):
    """Concrete state machine for disaster response dispatch.

    Maintains in-memory dicts of all domain entities. Applied log entries
    mutate this state deterministically. Every ICP running this state
    machine with the same log entries will have identical state.

    State:
        resources: dict[str, Resource] — all registered resources
        zones: dict[str, DisasterZone] — all registered disaster zones
        incidents: dict[str, Incident] — all reported incidents
        dispatches: dict[str, DispatchOrder] — all dispatch orders
        _last_applied: int — index of last applied log entry
    """

    def __init__(self) -> None:
        self.resources: dict[str, Resource] = {}
        self.zones: dict[str, DisasterZone] = {}
        self.incidents: dict[str, Incident] = {}
        self.dispatches: dict[str, DispatchOrder] = {}
        self._last_applied: int = 0

    def apply(self, entry: LogEntry) -> Any:
        """Apply a committed log entry to the dispatch state machine.

        Routes to the appropriate handler based on command_type.
        Must be deterministic — no randomness, no I/O.

        Args:
            entry: The committed log entry.

        Returns:
            Result of the command application.
        """
        if entry.command_type == CommandType.NOOP:
            self._last_applied = entry.index
            return {"status": "ok", "command": "noop"}

        payload = json.loads(entry.payload)

        handlers = {
            CommandType.RESOURCE_REGISTER: self._apply_resource_register,
            CommandType.RESOURCE_DISPATCH: self._apply_resource_dispatch,
            CommandType.RESOURCE_ARRIVE: self._apply_resource_arrive,
            CommandType.RESOURCE_RETURN: self._apply_resource_return,
            CommandType.RESOURCE_RESUPPLY_REQUEST: self._apply_resource_resupply_request,
            CommandType.RESOURCE_RESUPPLY_COMPLETE: self._apply_resource_resupply_complete,
            CommandType.RESOURCE_MAINTENANCE: self._apply_resource_maintenance,
            CommandType.RESOURCE_RESTORE: self._apply_resource_restore,
            CommandType.RESOURCE_CANCEL_DISPATCH: self._apply_resource_cancel_dispatch,
            CommandType.ZONE_REGISTER: self._apply_zone_register,
            CommandType.ZONE_UPDATE: self._apply_zone_update,
            CommandType.ZONE_PRIORITY_UPDATE: self._apply_zone_priority_update,
            CommandType.INCIDENT_REPORT: self._apply_incident_report,
            CommandType.INCIDENT_UPDATE: self._apply_incident_update,
            CommandType.INCIDENT_RESOLVE: self._apply_incident_resolve,
            CommandType.DISPATCH_ORDER: self._apply_dispatch_order,
            CommandType.DISPATCH_CONFIRM: self._apply_dispatch_confirm,
            CommandType.DISPATCH_REJECT: self._apply_dispatch_reject,
        }

        handler = handlers.get(entry.command_type)
        if handler is None:
            logger.warning(
                "unknown_command_type",
                command_type=entry.command_type,
                index=entry.index,
            )
            self._last_applied = entry.index
            return {"status": "error", "message": f"Unknown command type: {entry.command_type}"}

        try:
            result = handler(payload, entry)
            self._last_applied = entry.index
            return result
        except (ValueError, KeyError) as e:
            logger.error(
                "state_machine_apply_error",
                command_type=entry.command_type,
                index=entry.index,
                error=str(e),
            )
            self._last_applied = entry.index
            return {"status": "error", "message": str(e)}

    def snapshot(self) -> bytes:
        """Serialize the complete state machine state.

        Returns:
            JSON-encoded bytes of all state.
        """
        state = {
            "resources": {rid: r.model_dump(mode="json") for rid, r in self.resources.items()},
            "zones": {zid: z.model_dump(mode="json") for zid, z in self.zones.items()},
            "incidents": {iid: i.model_dump(mode="json") for iid, i in self.incidents.items()},
            "dispatches": {did: d.model_dump(mode="json") for did, d in self.dispatches.items()},
            "last_applied": self._last_applied,
        }
        return json.dumps(state).encode("utf-8")

    def restore(self, data: bytes) -> None:
        """Restore state machine from a snapshot.

        Args:
            data: JSON-encoded bytes from snapshot().
        """
        state = json.loads(data.decode("utf-8"))
        self.resources = {
            rid: Resource.model_validate(rdata)
            for rid, rdata in state["resources"].items()
        }
        self.zones = {
            zid: DisasterZone.model_validate(zdata)
            for zid, zdata in state["zones"].items()
        }
        self.incidents = {
            iid: Incident.model_validate(idata)
            for iid, idata in state["incidents"].items()
        }
        self.dispatches = {
            did: DispatchOrder.model_validate(ddata)
            for did, ddata in state["dispatches"].items()
        }
        self._last_applied = state["last_applied"]

    def last_applied_index(self) -> int:
        """Return the index of the last applied log entry."""
        return self._last_applied

    # ========================================================================
    # Resource Handlers
    # ========================================================================

    def _apply_resource_register(self, payload: dict, entry: LogEntry) -> dict:
        """Register a new resource."""
        resource = Resource.model_validate(payload)
        resource.raft_log_index = entry.index
        self.resources[resource.id] = resource
        return {"status": "ok", "resource_id": resource.id}

    def _apply_resource_dispatch(self, payload: dict, entry: LogEntry) -> dict:
        """Dispatch a resource to a zone (AVAILABLE → DISPATCHED)."""
        transition = ResourceStateTransition.model_validate(payload)
        transition.validate_transition()

        resource = self.resources.get(transition.resource_id)
        if resource is None:
            raise KeyError(f"Resource not found: {transition.resource_id}")

        if resource.status != ResourceStatus.AVAILABLE:
            raise ValueError(
                f"Resource {resource.id} is {resource.status}, not AVAILABLE. "
                "Cannot dispatch — this would be a double-dispatch."
            )

        resource.status = ResourceStatus.DISPATCHED
        resource.assigned_zone_id = transition.zone_id
        resource.assigned_incident_id = transition.incident_id
        resource.dispatched_by = transition.actor_id
        resource.last_transition_at = transition.timestamp
        resource.raft_log_index = entry.index

        # Update zone resource tracking
        if transition.zone_id and transition.zone_id in self.zones:
            zone = self.zones[transition.zone_id]
            if resource.id not in zone.assigned_resource_ids:
                zone.assigned_resource_ids.append(resource.id)
            zone.resources_en_route += 1

        return {"status": "ok", "resource_id": resource.id, "zone_id": transition.zone_id}

    def _apply_resource_arrive(self, payload: dict, entry: LogEntry) -> dict:
        """Resource arrives on scene (DISPATCHED → ON_SCENE)."""
        transition = ResourceStateTransition.model_validate(payload)
        transition.validate_transition()

        resource = self.resources.get(transition.resource_id)
        if resource is None:
            raise KeyError(f"Resource not found: {transition.resource_id}")

        resource.status = ResourceStatus.ON_SCENE
        resource.last_transition_at = transition.timestamp
        resource.raft_log_index = entry.index

        # Update zone tracking
        if resource.assigned_zone_id and resource.assigned_zone_id in self.zones:
            zone = self.zones[resource.assigned_zone_id]
            zone.resources_on_scene += 1
            zone.resources_en_route = max(0, zone.resources_en_route - 1)

        return {"status": "ok", "resource_id": resource.id}

    def _apply_resource_return(self, payload: dict, entry: LogEntry) -> dict:
        """Resource returning to base (ON_SCENE/DISPATCHED → RETURNING)."""
        transition = ResourceStateTransition.model_validate(payload)
        transition.validate_transition()

        resource = self.resources.get(transition.resource_id)
        if resource is None:
            raise KeyError(f"Resource not found: {transition.resource_id}")

        old_zone_id = resource.assigned_zone_id

        resource.status = ResourceStatus.RETURNING
        resource.last_transition_at = transition.timestamp
        resource.raft_log_index = entry.index

        # Update zone tracking
        if old_zone_id and old_zone_id in self.zones:
            zone = self.zones[old_zone_id]
            if resource.id in zone.assigned_resource_ids:
                zone.assigned_resource_ids.remove(resource.id)
            zone.resources_on_scene = max(0, zone.resources_on_scene - 1)

        return {"status": "ok", "resource_id": resource.id}

    def _apply_resource_resupply_request(self, payload: dict, entry: LogEntry) -> dict:
        """Resource needs resupply (ON_SCENE → NEEDS_RESUPPLY)."""
        transition = ResourceStateTransition.model_validate(payload)
        transition.validate_transition()

        resource = self.resources.get(transition.resource_id)
        if resource is None:
            raise KeyError(f"Resource not found: {transition.resource_id}")

        resource.status = ResourceStatus.NEEDS_RESUPPLY
        resource.last_transition_at = transition.timestamp
        resource.raft_log_index = entry.index

        return {"status": "ok", "resource_id": resource.id}

    def _apply_resource_resupply_complete(self, payload: dict, entry: LogEntry) -> dict:
        """Resource resupply complete (RESUPPLYING → AVAILABLE)."""
        transition = ResourceStateTransition.model_validate(payload)
        transition.validate_transition()

        resource = self.resources.get(transition.resource_id)
        if resource is None:
            raise KeyError(f"Resource not found: {transition.resource_id}")

        resource.status = ResourceStatus.AVAILABLE
        resource.assigned_zone_id = None
        resource.assigned_incident_id = None
        resource.dispatched_by = None
        resource.last_transition_at = transition.timestamp
        resource.raft_log_index = entry.index

        return {"status": "ok", "resource_id": resource.id}

    def _apply_resource_maintenance(self, payload: dict, entry: LogEntry) -> dict:
        """Take resource offline (AVAILABLE → MAINTENANCE)."""
        transition = ResourceStateTransition.model_validate(payload)
        transition.validate_transition()

        resource = self.resources.get(transition.resource_id)
        if resource is None:
            raise KeyError(f"Resource not found: {transition.resource_id}")

        resource.status = ResourceStatus.MAINTENANCE
        resource.last_transition_at = transition.timestamp
        resource.raft_log_index = entry.index

        return {"status": "ok", "resource_id": resource.id}

    def _apply_resource_restore(self, payload: dict, entry: LogEntry) -> dict:
        """Restore resource from maintenance (MAINTENANCE → AVAILABLE)."""
        transition = ResourceStateTransition.model_validate(payload)
        transition.validate_transition()

        resource = self.resources.get(transition.resource_id)
        if resource is None:
            raise KeyError(f"Resource not found: {transition.resource_id}")

        resource.status = ResourceStatus.AVAILABLE
        resource.last_transition_at = transition.timestamp
        resource.raft_log_index = entry.index

        return {"status": "ok", "resource_id": resource.id}

    def _apply_resource_cancel_dispatch(self, payload: dict, entry: LogEntry) -> dict:
        """Cancel a dispatch (DISPATCHED → AVAILABLE)."""
        transition = ResourceStateTransition.model_validate(payload)
        transition.validate_transition()

        resource = self.resources.get(transition.resource_id)
        if resource is None:
            raise KeyError(f"Resource not found: {transition.resource_id}")

        old_zone_id = resource.assigned_zone_id

        resource.status = ResourceStatus.AVAILABLE
        resource.assigned_zone_id = None
        resource.assigned_incident_id = None
        resource.dispatched_by = None
        resource.last_transition_at = transition.timestamp
        resource.raft_log_index = entry.index

        # Update zone tracking
        if old_zone_id and old_zone_id in self.zones:
            zone = self.zones[old_zone_id]
            if resource.id in zone.assigned_resource_ids:
                zone.assigned_resource_ids.remove(resource.id)
            zone.resources_en_route = max(0, zone.resources_en_route - 1)

        return {"status": "ok", "resource_id": resource.id}

    # ========================================================================
    # Zone Handlers
    # ========================================================================

    def _apply_zone_register(self, payload: dict, entry: LogEntry) -> dict:
        """Register a new disaster zone."""
        zone = DisasterZone.model_validate(payload)
        self.zones[zone.id] = zone
        return {"status": "ok", "zone_id": zone.id}

    def _apply_zone_update(self, payload: dict, entry: LogEntry) -> dict:
        """Update a zone's damage assessment and needs."""
        zone_id = payload["zone_id"]
        zone = self.zones.get(zone_id)
        if zone is None:
            raise KeyError(f"Zone not found: {zone_id}")

        # Apply partial updates
        for key, value in payload.items():
            if key != "zone_id" and hasattr(zone, key):
                setattr(zone, key, value)

        return {"status": "ok", "zone_id": zone_id}

    def _apply_zone_priority_update(self, payload: dict, entry: LogEntry) -> dict:
        """Update a zone's priority level."""
        zone_id = payload["zone_id"]
        zone = self.zones.get(zone_id)
        if zone is None:
            raise KeyError(f"Zone not found: {zone_id}")

        zone.priority = ZonePriority(payload["priority"])
        return {"status": "ok", "zone_id": zone_id, "priority": zone.priority}

    # ========================================================================
    # Incident Handlers
    # ========================================================================

    def _apply_incident_report(self, payload: dict, entry: LogEntry) -> dict:
        """Register a new incident."""
        incident = Incident.model_validate(payload)
        incident.status = IncidentStatus.ACTIVE
        self.incidents[incident.id] = incident
        return {"status": "ok", "incident_id": incident.id}

    def _apply_incident_update(self, payload: dict, entry: LogEntry) -> dict:
        """Update an incident."""
        incident_id = payload["incident_id"]
        incident = self.incidents.get(incident_id)
        if incident is None:
            raise KeyError(f"Incident not found: {incident_id}")

        for key, value in payload.items():
            if key != "incident_id" and hasattr(incident, key):
                setattr(incident, key, value)

        return {"status": "ok", "incident_id": incident_id}

    def _apply_incident_resolve(self, payload: dict, entry: LogEntry) -> dict:
        """Resolve an incident."""
        incident_id = payload["incident_id"]
        incident = self.incidents.get(incident_id)
        if incident is None:
            raise KeyError(f"Incident not found: {incident_id}")

        incident.status = IncidentStatus.CLOSED
        return {"status": "ok", "incident_id": incident_id}

    # ========================================================================
    # Dispatch Handlers
    # ========================================================================

    def _apply_dispatch_order(self, payload: dict, entry: LogEntry) -> dict:
        """Create a new dispatch order."""
        order = DispatchOrder.model_validate(payload)
        order.raft_log_index = entry.index
        self.dispatches[order.id] = order
        return {"status": "ok", "dispatch_id": order.id}

    def _apply_dispatch_confirm(self, payload: dict, entry: LogEntry) -> dict:
        """Confirm a dispatch order (IC gate passed)."""
        dispatch_id = payload["dispatch_id"]
        dispatch = self.dispatches.get(dispatch_id)
        if dispatch is None:
            raise KeyError(f"Dispatch order not found: {dispatch_id}")

        dispatch.status = DispatchStatus.CONFIRMED
        dispatch.commander_id = payload.get("commander_id")
        dispatch.commander_agency_id = payload.get("commander_agency_id")
        dispatch.confirmation_source = ConfirmationSource(
            payload.get("confirmation_source", "commander")
        )
        dispatch.committed_at = entry.timestamp
        dispatch.raft_log_index = entry.index

        return {"status": "ok", "dispatch_id": dispatch_id}

    def _apply_dispatch_reject(self, payload: dict, entry: LogEntry) -> dict:
        """Reject a dispatch order."""
        dispatch_id = payload["dispatch_id"]
        dispatch = self.dispatches.get(dispatch_id)
        if dispatch is None:
            raise KeyError(f"Dispatch order not found: {dispatch_id}")

        dispatch.status = DispatchStatus.REJECTED
        dispatch.commander_id = payload.get("commander_id")
        dispatch.commander_notes = payload.get("reason", "")

        return {"status": "ok", "dispatch_id": dispatch_id}

    # ========================================================================
    # Query Methods (for reads — not part of the apply path)
    # ========================================================================

    def get_available_resources(self) -> list[Resource]:
        """Return all resources with AVAILABLE status."""
        return [r for r in self.resources.values() if r.status == ResourceStatus.AVAILABLE]

    def get_zone_by_priority(self, priority: ZonePriority) -> list[DisasterZone]:
        """Return all zones with the given priority."""
        return [z for z in self.zones.values() if z.priority == priority]

    def get_unserved_zones(self) -> list[DisasterZone]:
        """Return zones with no assigned resources."""
        return [z for z in self.zones.values() if z.is_unserved]

    def get_resource(self, resource_id: str) -> Resource | None:
        """Get a resource by ID."""
        return self.resources.get(resource_id)

    def get_zone(self, zone_id: str) -> DisasterZone | None:
        """Get a zone by ID."""
        return self.zones.get(zone_id)
