"""
Route planning and obstacle avoidance engine under damaged infrastructure.

Roadmap v2 Task: M10
Calculates optimal routes, travel times (ETA), obstacle avoidance,
and ground vs. air transit requirements.
"""

from __future__ import annotations

import math
import time

from salus.models.dispatch import RouteResult
from salus.models.resource import Resource
from salus.models.zone import AccessStatus, DisasterZone


def calculate_haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in kilometers between two GPS coordinates using Haversine."""
    R = 6371.0  # Earth's radius in km
    rlat1, rlon1 = math.radians(lat1), math.radians(lon1)
    rlat2, rlon2 = math.radians(lat2), math.radians(lon2)

    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1

    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


class RoutePlanner:
    """Disaster-aware pathfinding and travel time estimator."""

    # Operational speeds (km/h)
    AIR_SPEED_KMH = 200.0  # Helicopter cruising speed
    GROUND_SPEED_OPEN_KMH = 50.0  # Ground speed on open roads
    GROUND_SPEED_RESTRICTED_KMH = 25.0  # Ground speed with debris/detours
    WATER_SPEED_KMH = 35.0  # Rescue boat speed

    def plan_route(
        self,
        resource: Resource,
        zone: DisasterZone,
    ) -> RouteResult:
        """Calculate the best route and ETA for a resource to reach a disaster zone.

        Args:
            resource: The responding resource.
            zone: The destination disaster zone.

        Returns:
            RouteResult with distance, travel time, obstacle details, and air requirements.
        """
        start_time = time.monotonic()

        r_loc = resource.current_location or resource.home_base
        z_loc = zone.boundary.center

        straight_distance = calculate_haversine_distance_km(
            r_loc.latitude, r_loc.longitude, z_loc.latitude, z_loc.longitude
        )

        obstacles: list[str] = []
        requires_air = False
        route_description = ""
        travel_time_minutes = 0.0
        actual_distance = straight_distance

        # Access evaluation
        if zone.access_status == AccessStatus.CUT_OFF:
            obstacles.append("All ground bridges/roads collapsed or severely blocked.")
            if resource.capabilities.can_access_air:
                requires_air = True
                route_description = (
                    f"Ground route severed. Direct air corridor from base to {zone.name}."
                )
                speed = self.AIR_SPEED_KMH
                travel_time_minutes = (straight_distance / speed) * 60.0
            else:
                route_description = (
                    f"INACCESSIBLE: Ground routes to {zone.name} are cut off. Requires engineering."
                )
                travel_time_minutes = float("inf")

        elif zone.access_status == AccessStatus.AIR_ONLY:
            requires_air = True
            obstacles.append("Ground approaches impassable; helicopter landing zone (LZ) required.")
            if resource.capabilities.can_access_air:
                route_description = f"Air corridor direct to {zone.name} LZ."
                speed = self.AIR_SPEED_KMH
                travel_time_minutes = (straight_distance / speed) * 60.0
            else:
                route_description = f"INACCESSIBLE: Zone requires air transport, but {resource.name} is ground-based."
                travel_time_minutes = float("inf")

        elif zone.access_status == AccessStatus.WATER_ONLY:
            obstacles.append("Flooding detected; road access inundated.")
            if resource.capabilities.can_access_water:
                route_description = f"Watercraft deployment via flood channels to {zone.name}."
                actual_distance = straight_distance * 1.3  # Channel winding factor
                speed = self.WATER_SPEED_KMH
                travel_time_minutes = (actual_distance / speed) * 60.0
            elif resource.capabilities.can_access_air:
                requires_air = True
                route_description = f"Airlift over flooded sector to {zone.name} dry LZ."
                speed = self.AIR_SPEED_KMH
                travel_time_minutes = (straight_distance / speed) * 60.0
            else:
                route_description = "INACCESSIBLE: Flooded zone requires water or air access."
                travel_time_minutes = float("inf")

        elif zone.access_status == AccessStatus.RESTRICTED:
            obstacles.append("Debris and partial road closures reported; bypass required.")
            if resource.capabilities.can_access_air:
                route_description = (
                    f"Direct air transit over restricted surface routes to {zone.name}."
                )
                speed = self.AIR_SPEED_KMH
                travel_time_minutes = (straight_distance / speed) * 60.0
            else:
                actual_distance = straight_distance * 1.4  # Detour factor
                speed = self.GROUND_SPEED_RESTRICTED_KMH
                travel_time_minutes = (actual_distance / speed) * 60.0
                route_description = f"Surface route with urban detours to {zone.name}."

        else:  # AccessStatus.OPEN
            if resource.capabilities.can_access_air:
                route_description = f"Direct air transit to {zone.name}."
                speed = self.AIR_SPEED_KMH
                travel_time_minutes = (straight_distance / speed) * 60.0
            else:
                actual_distance = straight_distance * 1.2  # Normal road network factor
                speed = self.GROUND_SPEED_OPEN_KMH
                travel_time_minutes = (actual_distance / speed) * 60.0
                route_description = f"Standard surface convoy route to {zone.name}."

        elapsed_ms = (time.monotonic() - start_time) * 1000.0

        return RouteResult(
            resource_id=resource.id,
            zone_id=zone.id,
            route_description=route_description,
            estimated_travel_time_minutes=round(travel_time_minutes, 1),
            distance_km=round(actual_distance, 1),
            obstacles=obstacles,
            requires_air=requires_air,
            latency_ms=round(elapsed_ms, 2),
        )
