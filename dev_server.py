"""
Salus Command Dashboard — Development & Preview Server

Runs a standalone HTTP server on port 8000 that serves:
1. Static dashboard files (HTML, CSS, JS) from ./dashboard
2. Mock REST API endpoints for /api/v1/cluster, /api/v1/resources,
   /api/v1/zones, and /api/v1/dispatch for interactive previewing
   without requiring the full Raft/LLM cluster.
"""

from __future__ import annotations

import json
import mimetypes
import os
import sys
import time
import uuid
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

DASHBOARD_DIR = Path(__file__).resolve().parent / "dashboard"
PORT = 8000

# Mock Cluster State
state = {
    "cluster": {
        "node_id": "alpha",
        "state": "leader",
        "current_term": 2,
        "leader_id": "alpha",
        "log_length": 14,
        "commit_index": 14,
        "last_applied": 14,
        "is_partitioned": False,
        "peers": ["bravo", "charlie"],
        "cluster_size": 3,
        "quorum_size": 2,
    },
    "resources": [
        {
            "id": "res-als-01",
            "name": "ALS Ambulance 101",
            "callsign": "ALS-101",
            "resource_type": "ambulance_als",
            "status": "available",
            "home_base": {"latitude": 28.582, "longitude": 77.214},
            "owning_agency_id": "agency-ems",
        },
        {
            "id": "res-fire-04",
            "name": "Heavy Fire Engine 4",
            "callsign": "ENG-04",
            "resource_type": "fire_engine",
            "status": "available",
            "home_base": {"latitude": 28.608, "longitude": 77.235},
            "owning_agency_id": "agency-fire",
        },
        {
            "id": "res-helo-01",
            "name": "Rescue Transport Helicopter",
            "callsign": "AIR-1",
            "resource_type": "helicopter_transport",
            "status": "available",
            "home_base": {"latitude": 28.553, "longitude": 77.195},
            "owning_agency_id": "agency-air",
        },
        {
            "id": "res-sar-01",
            "name": "Urban SAR Team Alpha",
            "callsign": "SAR-01",
            "resource_type": "sar_team_urban",
            "status": "available",
            "home_base": {"latitude": 28.625, "longitude": 77.228},
            "owning_agency_id": "agency-usar",
        },
        {
            "id": "res-haz-01",
            "name": "HAZMAT Response Unit 2",
            "callsign": "HAZ-02",
            "resource_type": "hazmat_team",
            "status": "available",
            "home_base": {"latitude": 28.571, "longitude": 77.242},
            "owning_agency_id": "agency-fire",
        },
        {
            "id": "res-k9-01",
            "name": "K9 Search Unit Echo",
            "callsign": "K9-05",
            "resource_type": "k9_unit",
            "status": "available",
            "home_base": {"latitude": 28.595, "longitude": 77.202},
            "owning_agency_id": "agency-police",
        },
    ],
    "zones": [
        {
            "id": "zone-cbd-01",
            "name": "Sector 4 — Central Business District",
            "priority": 1,
            "boundary": {
                "center": {"latitude": 28.618, "longitude": 77.219},
                "radius_km": 2.2,
            },
        },
        {
            "id": "zone-river-02",
            "name": "East Riverfront Lowlands",
            "priority": 2,
            "boundary": {
                "center": {"latitude": 28.568, "longitude": 77.248},
                "radius_km": 3.0,
            },
        },
        {
            "id": "zone-ind-03",
            "name": "North Industrial Corridor",
            "priority": 3,
            "boundary": {
                "center": {"latitude": 28.641, "longitude": 77.205},
                "radius_km": 1.8,
            },
        },
    ],
    "pending": [
        {
            "id": "conf-init-01",
            "resource_id": "res-als-01",
            "resource_name": "ALS Ambulance 101",
            "zone_id": "zone-cbd-01",
            "zone_name": "Sector 4 — Central Business District",
            "incident_id": "INC-7492",
            "ai_confidence": 0.94,
            "ai_reasoning": "Mass casualty triage at collapsed commercial structure. Closest ALS-certified unit with 4-min ETA.",
            "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=115)).isoformat(),
        }
    ],
}


class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler supporting both static dashboard files and mock API."""

    def log_message(self, format: str, *args: object) -> None:
        sys.stdout.write(f"[{self.log_date_time_string()}] {self.command} {self.path} -> {args[0]}\n")
        sys.stdout.flush()

    def _send_json(self, data: object, status: int = 200) -> None:
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        # REST API endpoints
        if path == "/api/v1/cluster/status":
            self._send_json(state["cluster"])
            return

        if path == "/api/v1/resources":
            self._send_json({"resources": state["resources"], "count": len(state["resources"])})
            return

        if path == "/api/v1/zones":
            self._send_json({"zones": state["zones"], "count": len(state["zones"])})
            return

        if path == "/api/v1/dispatch/pending":
            self._send_json({"pending": state["pending"], "count": len(state["pending"])})
            return

        if path == "/api/v1/audit":
            self._send_json({"entries": state.get("audit", []), "count": len(state.get("audit", []))})
            return

        # Static files
        if path in ("/", "/dashboard", "/dashboard/"):
            rel_path = "index.html"
        elif path.startswith("/dashboard/"):
            rel_path = path[len("/dashboard/") :]
        else:
            rel_path = path.lstrip("/")

        file_path = (DASHBOARD_DIR / rel_path).resolve()

        # Security check: must be inside DASHBOARD_DIR
        try:
            file_path.relative_to(DASHBOARD_DIR)
        except ValueError:
            self.send_error(403, "Access denied")
            return

        if not file_path.is_file():
            self.send_error(404, f"File not found: {rel_path}")
            return

        ctype, _ = mimetypes.guess_type(str(file_path))
        ctype = ctype or "application/octet-stream"

        try:
            with open(file_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(content)
        except OSError:
            self.send_error(500, "Error reading file")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        content_len = int(self.headers.get("Content-Length", 0))
        body = {}
        if content_len > 0:
            try:
                body = json.loads(self.rfile.read(content_len).decode("utf-8"))
            except Exception:
                pass

        if path.startswith("/api/v1/dispatch/") and path.endswith("/confirm"):
            conf_id = path.split("/")[4]
            # Remove from pending and mark resource dispatched
            state["pending"] = [p for p in state["pending"] if p.get("id") != conf_id]
            state["cluster"]["log_length"] += 1
            self._send_json({"status": "accepted", "log_index": state["cluster"]["log_length"]})
            return

        if path.startswith("/api/v1/dispatch/") and path.endswith("/reject"):
            conf_id = path.split("/")[4]
            state["pending"] = [p for p in state["pending"] if p.get("id") != conf_id]
            self._send_json({"status": "rejected", "confirmation_id": conf_id})
            return

        if path == "/api/v1/dispatch/run-pipeline":
            # Add a simulated pending confirmation from AI pipeline
            new_id = f"conf-{int(time.time())}"
            incident_id = body.get("incident_id", "INC-AUTO")
            zone_id = body.get("zone_id", "zone-cbd-01")
            zone_name = next((z["name"] for z in state["zones"] if z["id"] == zone_id), zone_id)
            rec_resource = state["resources"][len(state["pending"]) % len(state["resources"])]

            new_conf = {
                "id": new_id,
                "resource_id": rec_resource["id"],
                "resource_name": rec_resource["name"],
                "zone_id": zone_id,
                "zone_name": zone_name,
                "incident_id": incident_id,
                "ai_confidence": 0.88,
                "ai_reasoning": f"AI pipeline recommendation for {body.get('incident_description', 'incident')[:60]}...",
                "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat(),
            }
            state["pending"].append(new_conf)

            self._send_json(
                {
                    "status": "pipeline_complete",
                    "dispatch_order": {
                        "decision_confidence": 0.88,
                        "recommended_resource_name": rec_resource["name"],
                        "zone_id": zone_id,
                    },
                }
            )
            return

        if path == "/api/v1/resources":
            res_data = body.get("resource", {})
            res_data["id"] = res_data.get("id") or f"res-{uuid.uuid4().hex[:6]}"
            state["resources"].append(res_data)
            state["cluster"]["log_length"] += 1
            self._send_json({"status": "accepted", "resource_id": res_data["id"]})
            return

        self.send_error(404, f"API endpoint not found: {path}")


def run() -> None:
    server_address = ("127.0.0.1", PORT)
    httpd = HTTPServer(server_address, DashboardHandler)
    print(f"============================================================")
    print(f"  Salus Command Dashboard Preview Server")
    print(f"  URL: http://localhost:{PORT}/")
    print(f"  Mount: http://localhost:{PORT}/dashboard/")
    print(f"  API: http://localhost:{PORT}/api/v1/cluster/status")
    print(f"============================================================")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        httpd.server_close()


if __name__ == "__main__":
    run()
