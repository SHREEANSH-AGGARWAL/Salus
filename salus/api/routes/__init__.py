"""API routes package."""

from salus.api.routes.audit import router as audit_router
from salus.api.routes.cluster import router as cluster_router
from salus.api.routes.dispatch import router as dispatch_router
from salus.api.routes.resources import router as resources_router
from salus.api.routes.zones import router as zones_router

__all__ = [
    "audit_router",
    "cluster_router",
    "dispatch_router",
    "resources_router",
    "zones_router",
]
