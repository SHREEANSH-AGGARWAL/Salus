"""
Salus Full-Scale Mass Casualty Simulation.

Acts as the "World State" — generates 10 disaster zones and 30 diverse resources,
seeds the cluster, triggers a massive earthquake affecting 4 zones simultaneously,
fires 4 parallel AI pipeline requests, auto-confirms all dispatches, and reports
latency metrics (P50, P95, P99) and throughput.

Requirements:
    - A running Salus cluster (docker compose up, or local salus-node instances)
    - The AI pipeline extras installed (pip install 'salus[ai]')

Usage:
    python simulate_mass_casualty.py [--api-url http://localhost:8001]
"""

from __future__ import annotations

import argparse
import asyncio
import math
import statistics
import sys
import time

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.table import Table

from simulation.generators import generate_resources, generate_zones

console = Console()

# ============================================================================
# Configuration
# ============================================================================

DEFAULT_API = "http://localhost:8001"
NUM_ZONES = 10
NUM_RESOURCES = 30
NUM_EARTHQUAKE_ZONES = 4
COMMANDER_ID = "IC-SimCommander"
COMMANDER_AGENCY = "simulation"
REQUEST_TIMEOUT = 60.0


# ============================================================================
# Utility
# ============================================================================


def percentile(data: list[float], pct: float) -> float:
    """Calculate percentile from sorted data."""
    if not data:
        return 0.0
    k = (len(data) - 1) * (pct / 100)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return data[int(k)]
    return data[f] * (c - k) + data[c] * (k - f)


# ============================================================================
# Cluster Connection
# ============================================================================


async def connect_to_cluster(client: httpx.AsyncClient, api_url: str) -> dict:
    """Verify the cluster is running and return its status."""
    console.print(Panel(
        "[bold cyan]SALUS MASS CASUALTY SIMULATION[/bold cyan]\n"
        "Full-scale disaster response system test",
        border_style="cyan",
    ))

    try:
        resp = await client.get(f"{api_url}/api/v1/cluster/status")
        resp.raise_for_status()
        status = resp.json()
        state = status.get("state", "unknown")
        if hasattr(state, "value"):
            state = state.value
        console.print(
            f"[green]✓ Connected to [bold]{status.get('node_id', '?')}[/bold] "
            f"(state: {state}, term: {status.get('current_term', '?')})[/green]"
        )
        return status
    except httpx.ConnectError:
        console.print(
            f"[bold red]✗ Cannot connect to {api_url}[/bold red]\n\n"
            "[yellow]Make sure the Salus cluster is running:[/yellow]\n"
            "  [dim]docker compose up --build[/dim]\n"
            "  [dim]— or —[/dim]\n"
            "  [dim]salus-node  (run 3 instances with different SALUS_NODE_ID)[/dim]\n"
        )
        sys.exit(1)
    except Exception as e:
        console.print(f"[bold red]✗ Cluster error: {e}[/bold red]")
        sys.exit(1)


# ============================================================================
# Seeding
# ============================================================================


async def seed_cluster(
    client: httpx.AsyncClient, api_url: str
) -> tuple[list, list]:
    """Register zones and resources into the cluster."""
    console.print("\n[bold yellow]═══ PHASE 1: SEEDING WORLD STATE ═══[/bold yellow]")

    zones = generate_zones(n=NUM_ZONES, seed=42)
    resources = generate_resources(n=NUM_RESOURCES, seed=42)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        # Register zones
        zone_task = progress.add_task("Registering zones...", total=len(zones))
        zone_ids = []
        for z in zones:
            try:
                resp = await client.post(
                    f"{api_url}/api/v1/zones",
                    json={"zone": z.model_dump(mode="json")},
                )
                if resp.status_code in (200, 201):
                    zone_ids.append(z.id)
                elif resp.status_code == 409:
                    # Redirect to leader — try to get leader info
                    detail = resp.json().get("detail", {})
                    if isinstance(detail, dict) and detail.get("leader_id"):
                        console.print(f"[red]⚠ Not the leader. Leader: {detail['leader_id']}[/red]")
                    break
            except Exception as e:
                console.print(f"[dim red]Zone {z.name}: {e}[/dim red]")
            progress.advance(zone_task)

        # Register resources
        res_task = progress.add_task("Registering resources...", total=len(resources))
        resource_ids = []
        for r in resources:
            try:
                resp = await client.post(
                    f"{api_url}/api/v1/resources",
                    json={"resource": r.model_dump(mode="json")},
                )
                if resp.status_code in (200, 201):
                    resource_ids.append(r.id)
                elif resp.status_code == 409:
                    break
            except Exception as e:
                console.print(f"[dim red]Resource {r.name}: {e}[/dim red]")
            progress.advance(res_task)

    console.print(
        f"[green]✓ Seeded {len(zone_ids)} zones and {len(resource_ids)} resources[/green]"
    )

    # Display zone table
    zone_table = Table(title="Registered Disaster Zones", border_style="dim")
    zone_table.add_column("Zone", style="cyan")
    zone_table.add_column("Code", style="dim")
    zone_table.add_column("Priority", style="bold")
    zone_table.add_column("Damage", style="yellow")
    for z in zones[:len(zone_ids)]:
        p_color = {1: "red", 2: "yellow", 3: "cyan", 4: "green", 5: "dim"}.get(z.priority, "white")
        zone_table.add_row(z.name, z.zone_code, f"[{p_color}]P{z.priority}[/{p_color}]", z.damage_level)
    console.print(zone_table)

    return zones[:len(zone_ids)], resources[:len(resource_ids)]


# ============================================================================
# Earthquake Trigger
# ============================================================================


EARTHQUAKE_DESCRIPTIONS = [
    (
        "A devastating 7.2 magnitude earthquake has struck the Old City Market district. "
        "Dense market area with narrow lanes — multiple old buildings collapsed. "
        "Estimated 45 people trapped under rubble. Fires breaking out from ruptured gas lines. "
        "Main access roads blocked by debris."
    ),
    (
        "Severe structural collapse in the Residential East district following the earthquake. "
        "Multi-story apartment complexes showing pancake collapse patterns. "
        "Estimated 120 injured, 30 trapped. Emergency medical triage needed urgently. "
        "Water mains broken, flooding ground floors."
    ),
    (
        "Industrial Park devastated — chemical storage facility breached by earthquake tremors. "
        "Toxic fumes spreading downwind. Factory walls collapsed onto worker dormitories. "
        "HAZMAT containment urgently required. Ground routes partially blocked by overturned trucks."
    ),
    (
        "Hospital District emergency: The main regional hospital has suffered severe structural "
        "damage. ICU and operating theaters compromised. 200+ patients need evacuation. "
        "Back-up generators failing. Surrounding care homes reporting casualties."
    ),
]


async def run_earthquake_simulation(
    client: httpx.AsyncClient,
    api_url: str,
    zones: list,
    resources: list,
) -> list[dict]:
    """Fire 4 parallel AI pipeline requests and auto-confirm all dispatches."""
    console.print("\n[bold red]═══ PHASE 2: EARTHQUAKE STRIKES ═══[/bold red]")
    console.print("[red]⚠ 7.2 MAGNITUDE EARTHQUAKE — 4 ZONES AFFECTED[/red]\n")

    target_zones = zones[:NUM_EARTHQUAKE_ZONES]

    # Show affected zones
    for i, z in enumerate(target_zones):
        console.print(f"  [red]🔴 Zone {i+1}:[/red] [bold]{z.name}[/bold] — P{z.priority}")

    console.print()

    # ── Fire parallel pipeline requests ──
    console.print("[yellow]Launching 4 parallel AI pipeline requests...[/yellow]")

    pipeline_latencies: list[float] = []
    pipeline_results: list[dict] = []

    t_overall_start = time.perf_counter()

    async def run_pipeline(idx: int, zone, description: str) -> dict | None:
        t_start = time.perf_counter()
        try:
            resp = await client.post(
                f"{api_url}/api/v1/dispatch/run-pipeline",
                json={
                    "incident_id": f"inc-eq-sim-{idx:03d}",
                    "zone_id": zone.id,
                    "incident_description": description,
                },
                timeout=REQUEST_TIMEOUT,
            )
            t_elapsed = (time.perf_counter() - t_start) * 1000
            pipeline_latencies.append(t_elapsed)

            if resp.status_code == 200:
                result = resp.json()
                console.print(
                    f"  [green]✓[/green] Pipeline {idx+1}: "
                    f"[cyan]{result.get('dispatch_order', {}).get('assigned_resource_name', 'N/A')}[/cyan] "
                    f"→ {zone.name} "
                    f"({t_elapsed:.0f}ms, "
                    f"conf: {result.get('dispatch_order', {}).get('decision_confidence', 0) * 100:.0f}%)"
                )
                return result
            elif resp.status_code == 503:
                console.print(
                    f"  [yellow]⚠[/yellow] Pipeline {idx+1}: AI pipeline not available "
                    f"(install salus[ai] extras). Status: {resp.status_code}"
                )
                return None
            else:
                err = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                console.print(
                    f"  [red]✗[/red] Pipeline {idx+1}: {resp.status_code} — {err.get('detail', 'Unknown error')}"
                )
                return None
        except httpx.ReadTimeout:
            t_elapsed = (time.perf_counter() - t_start) * 1000
            pipeline_latencies.append(t_elapsed)
            console.print(f"  [red]✗[/red] Pipeline {idx+1}: Timeout ({t_elapsed:.0f}ms)")
            return None
        except Exception as e:
            t_elapsed = (time.perf_counter() - t_start) * 1000
            pipeline_latencies.append(t_elapsed)
            console.print(f"  [red]✗[/red] Pipeline {idx+1}: {e}")
            return None

    results = await asyncio.gather(*[
        run_pipeline(i, target_zones[i], EARTHQUAKE_DESCRIPTIONS[i])
        for i in range(NUM_EARTHQUAKE_ZONES)
    ])

    t_overall = (time.perf_counter() - t_overall_start) * 1000

    pipeline_results = [r for r in results if r is not None]
    console.print(f"\n[green]Pipeline phase complete: {len(pipeline_results)}/{NUM_EARTHQUAKE_ZONES} succeeded ({t_overall:.0f}ms)[/green]")

    # ── Auto-confirm dispatches ──
    if pipeline_results:
        console.print("\n[yellow]Auto-confirming dispatches...[/yellow]")

        confirm_latencies: list[float] = []
        confirmed_count = 0

        for result in pipeline_results:
            confirmation_id = result.get("confirmation_id")
            if not confirmation_id:
                continue

            t_start = time.perf_counter()
            try:
                resp = await client.post(
                    f"{api_url}/api/v1/dispatch/{confirmation_id}/confirm",
                    json={
                        "commander_id": COMMANDER_ID,
                        "commander_agency_id": COMMANDER_AGENCY,
                        "notes": "Auto-confirmed by mass casualty simulation",
                    },
                    timeout=10.0,
                )
                t_elapsed = (time.perf_counter() - t_start) * 1000
                confirm_latencies.append(t_elapsed)

                if resp.status_code == 200:
                    data = resp.json()
                    confirmed_count += 1
                    console.print(
                        f"  [green]✓[/green] Confirmed: {data.get('resource_id', '?')} → "
                        f"zone {data.get('zone_id', '?')} "
                        f"(Raft log #{data.get('log_index', '?')}, {t_elapsed:.0f}ms)"
                    )
                else:
                    err = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                    console.print(
                        f"  [red]✗[/red] Confirm failed: {err.get('detail', resp.status_code)}"
                    )
            except Exception as e:
                t_elapsed = (time.perf_counter() - t_start) * 1000
                confirm_latencies.append(t_elapsed)
                console.print(f"  [red]✗[/red] Confirm error: {e}")

        console.print(f"[green]✓ Confirmed {confirmed_count}/{len(pipeline_results)} dispatches[/green]")
    else:
        confirm_latencies = []

    return {
        "pipeline_latencies": pipeline_latencies,
        "confirm_latencies": confirm_latencies if pipeline_results else [],
        "overall_ms": t_overall,
        "pipeline_count": len(pipeline_results),
        "total_attempted": NUM_EARTHQUAKE_ZONES,
    }


# ============================================================================
# Metrics Report
# ============================================================================


def print_metrics(metrics: dict, zones: list, api_url: str):
    """Print a rich terminal report of simulation results."""
    console.print("\n[bold magenta]═══ PHASE 3: METRICS REPORT ═══[/bold magenta]")

    pl = sorted(metrics["pipeline_latencies"])
    cl = sorted(metrics.get("confirm_latencies", []))
    all_latencies = sorted(pl + cl)

    if pl:
        latency_table = Table(title="Latency Metrics (ms)", border_style="magenta")
        latency_table.add_column("Metric", style="cyan")
        latency_table.add_column("Pipeline", justify="right", style="yellow")
        latency_table.add_column("Confirm", justify="right", style="green")
        latency_table.add_column("End-to-End", justify="right", style="bold")

        def fmt(data, p):
            return f"{percentile(data, p):.1f}" if data else "—"

        latency_table.add_row("P50 (median)", fmt(pl, 50), fmt(cl, 50), fmt(all_latencies, 50))
        latency_table.add_row("P95", fmt(pl, 95), fmt(cl, 95), fmt(all_latencies, 95))
        latency_table.add_row("P99", fmt(pl, 99), fmt(cl, 99), fmt(all_latencies, 99))
        latency_table.add_row("Min", fmt(pl, 0), fmt(cl, 0), fmt(all_latencies, 0))
        latency_table.add_row("Max", f"{max(pl):.1f}" if pl else "—", f"{max(cl):.1f}" if cl else "—", f"{max(all_latencies):.1f}" if all_latencies else "—")
        latency_table.add_row("Mean", f"{statistics.mean(pl):.1f}" if pl else "—", f"{statistics.mean(cl):.1f}" if cl else "—", f"{statistics.mean(all_latencies):.1f}" if all_latencies else "—")

        console.print(latency_table)

    # Throughput
    total_dispatches = metrics["pipeline_count"]
    overall_s = metrics["overall_ms"] / 1000
    throughput = total_dispatches / overall_s if overall_s > 0 else 0

    throughput_table = Table(title="Throughput", border_style="green")
    throughput_table.add_column("Metric", style="cyan")
    throughput_table.add_column("Value", justify="right", style="bold")
    throughput_table.add_row("Dispatches attempted", str(metrics["total_attempted"]))
    throughput_table.add_row("Dispatches succeeded", str(total_dispatches))
    throughput_table.add_row("Wall clock time", f"{overall_s:.2f}s")
    throughput_table.add_row("Throughput", f"{throughput:.2f} dispatches/s")

    console.print(throughput_table)

    # Summary
    if total_dispatches == metrics["total_attempted"]:
        console.print(Panel(
            f"[bold green]✅ SIMULATION PASSED[/bold green]\n"
            f"All {total_dispatches} dispatches committed successfully.\n"
            f"P99 latency: {fmt(all_latencies, 99)}ms | Throughput: {throughput:.2f}/s",
            border_style="green",
        ))
    elif total_dispatches > 0:
        console.print(Panel(
            f"[bold yellow]⚠ PARTIAL SUCCESS[/bold yellow]\n"
            f"{total_dispatches}/{metrics['total_attempted']} dispatches committed.\n"
            f"Some pipelines may have failed (check AI extras installation).",
            border_style="yellow",
        ))
    else:
        console.print(Panel(
            f"[bold red]✗ SIMULATION FAILED[/bold red]\n"
            "No dispatches were committed. Check:\n"
            "  1. Is the cluster running? (docker compose up)\n"
            "  2. Are AI extras installed? (pip install 'salus[ai]')\n"
            "  3. Is this node the leader? (check /api/v1/cluster/status)",
            border_style="red",
        ))


# ============================================================================
# Final Audit
# ============================================================================


async def print_final_state(client: httpx.AsyncClient, api_url: str):
    """Print final resource allocation and zone status."""
    console.print("\n[bold blue]═══ FINAL CLUSTER STATE ═══[/bold blue]")

    try:
        res_resp = await client.get(f"{api_url}/api/v1/resources")
        if res_resp.status_code == 200:
            resources = res_resp.json().get("resources", [])
            dispatched = [r for r in resources if r.get("status") == "dispatched"]
            available = [r for r in resources if r.get("status") == "available"]

            res_table = Table(title=f"Resource Allocation ({len(dispatched)} dispatched / {len(resources)} total)", border_style="blue")
            res_table.add_column("Resource", style="cyan")
            res_table.add_column("Type", style="dim")
            res_table.add_column("Status", style="bold")
            res_table.add_column("Zone", style="yellow")

            for r in dispatched:
                res_table.add_row(
                    r.get("name", r.get("id", "?")),
                    r.get("resource_type", "?"),
                    "[green]DISPATCHED[/green]",
                    r.get("assigned_zone_id", "—"),
                )

            # Show a few available resources
            for r in available[:5]:
                res_table.add_row(
                    r.get("name", r.get("id", "?")),
                    r.get("resource_type", "?"),
                    "[dim]AVAILABLE[/dim]",
                    "—",
                )
            if len(available) > 5:
                res_table.add_row(f"... +{len(available) - 5} more", "", "[dim]AVAILABLE[/dim]", "—")

            console.print(res_table)

            # Double-dispatch check
            dispatched_ids = [r.get("id") for r in dispatched]
            unique_ids = set(dispatched_ids)
            if len(dispatched_ids) != len(unique_ids):
                console.print("[bold red]⚠ DOUBLE-DISPATCH DETECTED! This is a critical safety violation.[/bold red]")
            else:
                console.print(f"[green]✓ No double-dispatches detected ({len(unique_ids)} unique dispatches)[/green]")

    except Exception as e:
        console.print(f"[red]Could not fetch final state: {e}[/red]")

    # Audit trail
    try:
        audit_resp = await client.get(f"{api_url}/api/v1/audit")
        if audit_resp.status_code == 200:
            entries = audit_resp.json().get("entries", [])
            if entries:
                console.print(f"\n[dim]Audit log: {len(entries)} entries recorded[/dim]")
    except Exception:
        pass


# ============================================================================
# Main
# ============================================================================


async def run(api_url: str):
    """Execute the full mass casualty simulation."""
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        # Phase 0: Connect
        await connect_to_cluster(client, api_url)

        # Phase 1: Seed
        zones, resources = await seed_cluster(client, api_url)
        if not zones:
            console.print("[red]No zones registered. Aborting simulation.[/red]")
            return

        # Phase 2: Earthquake
        metrics = await run_earthquake_simulation(client, api_url, zones, resources)

        # Phase 3: Metrics
        print_metrics(metrics, zones, api_url)

        # Final state
        await print_final_state(client, api_url)

    console.print("\n[dim]Simulation complete.[/dim]")


def main():
    parser = argparse.ArgumentParser(
        description="Salus Mass Casualty Simulation — Full-scale disaster response test",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--api-url",
        default=DEFAULT_API,
        help=f"Base URL of the Salus cluster leader API (default: {DEFAULT_API})",
    )
    args = parser.parse_args()

    try:
        asyncio.run(run(args.api_url))
    except KeyboardInterrupt:
        console.print("\n[yellow]Simulation interrupted.[/yellow]")
        sys.exit(0)


if __name__ == "__main__":
    main()
