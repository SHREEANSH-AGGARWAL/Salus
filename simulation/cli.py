"""
CLI tool for disaster response simulation and cluster population.

Provides commands to:
    - seed: Populate a running cluster with realistic zones and resources
    - status: Print rich terminal dashboard of cluster and resource states
    - scenario: Run automated disaster incident and dispatch scenarios
"""

from __future__ import annotations

import argparse
import sys
import time

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from simulation.generators import generate_resources, generate_zones

console = Console()


def cmd_seed(args: argparse.Namespace) -> None:
    """Seed the cluster with disaster zones and resources via the REST API."""
    api_url = args.api_url.rstrip("/")
    console.print(f"[bold cyan]Seeding cluster via {api_url}...[/bold cyan]")

    zones = generate_zones(n=args.zones, seed=args.seed)
    resources = generate_resources(n=args.resources, seed=args.seed)

    with httpx.Client(timeout=10.0) as client:
        # Check cluster leader first
        try:
            status_resp = client.get(f"{api_url}/api/v1/cluster/status")
            status_resp.raise_for_status()
            cluster_info = status_resp.json()
            console.print(
                f"[green]Connected to node [bold]{cluster_info.get('node_id')}[/bold] "
                f"(state: {cluster_info.get('state')}, term: {cluster_info.get('current_term')})[/green]"
            )
        except Exception as e:
            console.print(f"[bold red]Failed to connect to {api_url}: {e}[/bold red]")
            sys.exit(1)

        # 1. Register Zones
        console.print(f"\n[yellow]Registering {len(zones)} disaster zones...[/yellow]")
        zones_created = 0
        for z in zones:
            try:
                resp = client.post(
                    f"{api_url}/api/v1/zones",
                    json={"zone": z.model_dump(mode="json")},
                )
                if resp.status_code in (200, 201):
                    zones_created += 1
                elif resp.status_code == 409:
                    console.print(f"[red]Redirect needed: {resp.json()}[/red]")
                    break
            except Exception as e:
                console.print(f"[red]Error registering zone {z.name}: {e}[/red]")

        console.print(f"[green]Successfully registered {zones_created}/{len(zones)} zones.[/green]")

        # 2. Register Resources
        console.print(f"\n[yellow]Registering {len(resources)} resources...[/yellow]")
        resources_created = 0
        for r in resources:
            try:
                resp = client.post(
                    f"{api_url}/api/v1/resources",
                    json={"resource": r.model_dump(mode="json")},
                )
                if resp.status_code in (200, 201):
                    resources_created += 1
                elif resp.status_code == 409:
                    console.print(f"[red]Redirect needed: {resp.json()}[/red]")
                    break
            except Exception as e:
                console.print(f"[red]Error registering resource {r.name}: {e}[/red]")

        console.print(f"[green]Successfully registered {resources_created}/{len(resources)} resources.[/green]")


def cmd_status(args: argparse.Namespace) -> None:
    """Print rich terminal status overview of the Salus cluster."""
    api_url = args.api_url.rstrip("/")

    with httpx.Client(timeout=5.0) as client:
        try:
            c_resp = client.get(f"{api_url}/api/v1/cluster/status")
            c_resp.raise_for_status()
            cluster = c_resp.json()

            res_resp = client.get(f"{api_url}/api/v1/resources")
            resources = res_resp.json().get("resources", [])
            partitioned = res_resp.json().get("partitioned", False)

            zones_resp = client.get(f"{api_url}/api/v1/zones")
            zones = zones_resp.json().get("zones", [])

            disp_resp = client.get(f"{api_url}/api/v1/dispatch/pending")
            pending = disp_resp.json().get("pending", [])

        except Exception as e:
            console.print(f"[bold red]Failed to fetch status from {api_url}: {e}[/bold red]")
            sys.exit(1)

    # Header Panel
    state_color = "green" if cluster.get("state") == "leader" else "cyan"
    mode_str = "[bold red]DEGRADED (PARTITIONED)[/bold red]" if partitioned else "[green]NORMAL QUORUM[/green]"

    console.print(
        Panel(
            f"[bold]Node ID:[/bold] {cluster.get('node_id')} | "
            f"[bold]State:[/bold] [{state_color}]{cluster.get('state')}[/{state_color}] | "
            f"[bold]Term:[/bold] {cluster.get('current_term')} | "
            f"[bold]Commit Index:[/bold] {cluster.get('commit_index')} | "
            f"[bold]Operating Mode:[/bold] {mode_str}\n"
            f"[bold]Cluster Size:[/bold] {cluster.get('cluster_size')} | "
            f"[bold]Quorum:[/bold] {cluster.get('quorum_size')} | "
            f"[bold]Peers:[/bold] {', '.join(cluster.get('peers', []))}",
            title="[bold red]Salus Incident Command Post Status[/bold red]",
            border_style="red",
        )
    )

    # Resources Table
    r_table = Table(title="Emergency Resources Status", show_header=True, header_style="bold magenta")
    r_table.add_column("Callsign", style="cyan")
    r_table.add_column("Name")
    r_table.add_column("Type")
    r_table.add_column("Status")
    r_table.add_column("Assigned Zone")

    for r in resources[:15]:
        status_style = "green" if r["status"] == "available" else "yellow"
        if r.get("is_uncertain") or r["status"] == "uncertain":
            status_style = "bold red"
        r_table.add_row(
            r.get("callsign", "N/A"),
            r.get("name", "N/A"),
            r.get("resource_type", "N/A"),
            f"[{status_style}]{r.get('status')}[/{status_style}]",
            r.get("assigned_zone_id") or "-",
        )

    console.print(r_table)

    # Zones Table
    z_table = Table(title="Disaster Zones Priority", show_header=True, header_style="bold blue")
    z_table.add_column("Code", style="cyan")
    z_table.add_column("Zone Name")
    z_table.add_column("Priority")
    z_table.add_column("Damage")
    z_table.add_column("Access")

    for z in zones[:10]:
        z_table.add_row(
            z.get("zone_code", "N/A"),
            z.get("name", "N/A"),
            str(z.get("priority", "N/A")),
            str(z.get("damage_level", "N/A")),
            str(z.get("access_status", "N/A")),
        )

    console.print(z_table)

    # Pending Confirmations
    if pending:
        console.print(f"\n[bold yellow]⚠️  {len(pending)} DISPATCH RECOMMENDATIONS AWAITING COMMANDER CONFIRMATION[/bold yellow]")
        for p in pending:
            console.print(
                f"  - ID: [bold]{p['id']}[/bold] | Resource: [cyan]{p['resource_name']}[/cyan] -> "
                f"Zone: [blue]{p['zone_name']}[/blue] (AI Confidence: {p.get('ai_confidence', 0.0):.2f})"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Salus Disaster Response Simulation CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Seed command
    seed_parser = subparsers.add_parser("seed", help="Seed cluster with synthetic data")
    seed_parser.add_argument("--api-url", default="http://localhost:8000", help="Salus node REST API URL")
    seed_parser.add_argument("--zones", type=int, default=10, help="Number of disaster zones")
    seed_parser.add_argument("--resources", type=int, default=25, help="Number of resources")
    seed_parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    seed_parser.set_defaults(func=cmd_seed)

    # Status command
    status_parser = subparsers.add_parser("status", help="Display cluster overview")
    status_parser.add_argument("--api-url", default="http://localhost:8000", help="Salus node REST API URL")
    status_parser.set_defaults(func=cmd_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
