# Salus — Disaster Response Resource Consensus Network



> A distributed backend system that coordinates real-time emergency resource allocation across multiple Incident Command Posts (ICPs) using Raft consensus to guarantee no resource is ever double-dispatched, even under network partition.

## The Problem

During a disaster, multiple Incident Command Posts simultaneously dispatch resources to affected zones. Under eventual consistency, an ICP may show a SAR team as "available" when it was dispatched 200ms ago by another ICP. Two commanders dispatch the same helicopter. A critical zone gets nothing. That is a coordination failure with lethal consequences.

**Salus makes double-dispatch structurally impossible** using Raft's linearizable writes.

## Architecture

```
ICP Alpha (Leader) ◄──► ICP Bravo (Follower) ◄──► ICP Charlie (Follower)
     │                        │                          │
  Raft Log                 Raft Log                   Raft Log
  RAG Index                RAG Index                  RAG Index
  Agent Pipeline           Agent Pipeline             Agent Pipeline
```

### Key Components

- **Raft Consensus** — Linearizable resource state transitions across all ICPs
- **5-Agent Pipeline** — Damage Assessment → Resource Matching → Routing → Protocol → Decision
- **Incident Commander Gate** — No autonomous dispatch; every resource deployment requires IC confirmation
- **Circuit-Breaker Fallback** — Rule-based dispatch when LLM is unavailable
- **Immutable Audit Log** — Full traceability of every AI recommendation and IC decision

## Quick Start

```bash
# Install core dependencies
pip install -e .

# Install with AI pipeline extras (optional — enables 5-agent LLM pipeline)
pip install -e ".[ai]"

# Start a single Salus ICP node
python -m salus.main

# Open the Command Dashboard
# http://localhost:8000/dashboard/
```

The dashboard is a vanilla HTML/CSS/JS single-page application served by the
FastAPI backend — no bundler, no npm required.

### The Command Dashboard

A dark tactical console built around an **interactive radar map of Delhi NCR** —
the NCT outline, the Yamuna, both ring roads, and landmarks from IGI to Chandni
Chowk drawn as a schematic you can drag, scroll to zoom, and click. Units and
disaster zones are plotted on it live; dispatch routes animate between them.

It is written for someone who has never seen this project. Every piece of
consensus jargon has a plain-language label and a hover explanation ("agreed
changes", not "commit index"), a guidance bar at the top always names the single
next thing worth doing, and `?` opens a glossary at any time.

#### Getting in

1. **Who is on duty** — commander ID and agency, pre-filled. This is attached to
   every approval you make and to every entry in the record.
2. **What is on the map** — load the Delhi scenario (12 emergency units and 6
   affected sectors, written through the real consensus API) or start empty.
   You can load the sample data later from the header at any time.

#### The four screens

| Screen | What it is for |
|--------|----------------|
| **Operations** | The radar map, the unit and zone lists, and a "right now" panel: units ready, en route, on scene, and urgent zones with nobody sent. |
| **Approvals** | Dispatch recommendations waiting on you — approve, send a different unit, or reject. Nothing moves until you decide. |
| **Network** | Consensus health in plain English, plus the raw indices for anyone who wants them. |
| **History** | The immutable audit trail: every AI recommendation and every human decision, in order. |

#### Dispatching

Two routes, both ending at the same human gate:

- **Plan a dispatch** (`P`) runs the 5-agent AI pipeline and hands you a
  recommendation with its reasoning and confidence.
- **Send a unit manually** (`M`) lets you pick the unit yourself — ready units
  sorted by distance to the zone. Use this when the AI extras are not installed.

Either way the proposal lands in **Approvals** and waits for a named human.

#### Map controls

Drag to pan · scroll or double-click to zoom · click a unit or zone for details ·
layer toggles for routes, landmarks, labels, range rings and the scan sweep ·
**Pick on map** in the add-unit and add-zone forms sets coordinates by clicking.

Keyboard: `1`–`4` screens · `/` search · `P` plan · `M` manual · `F` fit ·
`R` recentre on Delhi · `?` help · `Esc` close.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/cluster/status` | Raft node consensus status |
| GET | `/api/v1/cluster/health` | Liveness & readiness |
| GET | `/api/v1/cluster/peers` | Peer replication state |
| GET | `/api/v1/resources` | List all resources |
| POST | `/api/v1/resources` | Register resource via Raft |
| GET | `/api/v1/zones` | List all zones |
| POST | `/api/v1/zones` | Register zone via Raft |
| POST | `/api/v1/dispatch/run-pipeline` | Trigger 5-agent AI pipeline |
| GET | `/api/v1/dispatch/pending` | IC Gate pending queue |
| POST | `/api/v1/dispatch/{id}/confirm` | IC confirms dispatch |
| POST | `/api/v1/dispatch/{id}/reject` | IC rejects recommendation |
| POST | `/api/v1/dispatch/{id}/override` | IC overrides with different resource |
| GET | `/api/v1/audit` | Query immutable audit trail |
| WS | `/ws/events` | Real-time event stream |

## License

MIT — See [LICENSE](LICENSE)
