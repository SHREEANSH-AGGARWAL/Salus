# Salus — Disaster Response Resource Consensus Network

A distributed backend system for coordinating emergency resource allocation across multiple Incident Command Posts (ICPs). Salus uses a custom Raft consensus implementation to guarantee that no emergency resource (helicopter, SAR team, ambulance) is ever double-dispatched, even when ICPs are operating across degraded networks or partitioned segments of a mesh radio infrastructure.

---

## The Problem

During a large-scale disaster, multiple Incident Command Posts from different agencies (Fire, EMS, Urban SAR) operate simultaneously, each managing a subset of resources. Without strict coordination, the following failure modes occur under eventual consistency:

1. **Double-dispatch**: ICP-A and ICP-B both read a SAR team as "available" and dispatch it to different zones within a 200ms window. Both dispatches succeed locally. The team receives conflicting orders.
2. **Ghost availability**: A resource dispatched by ICP-A appears as "available" on ICP-B's interface for several seconds due to replication lag. A commander acts on stale data.
3. **Split-brain during partition**: Two ICPs, unable to communicate due to a downed relay, each elect themselves authoritative and make conflicting writes that cannot be merged.

Salus solves all three by making resource state transitions **strictly linearizable**: every dispatch is a consensus transaction that must be acknowledged by a quorum of nodes before it takes effect, and no node can commit a conflicting state.

---

## System Architecture

Each physical ICP machine runs a single `salus-node` process. This process hosts:

1. **Raft consensus engine** — manages the replicated log and leader election
2. **gRPC server** — handles inter-node Raft RPCs (AppendEntries, RequestVote, InstallSnapshot)
3. **FastAPI REST server** — exposes the HTTP API for Incident Commander tooling
4. **Domain state machine** — applies committed log entries to produce current resource/zone state
5. **AI dispatch pipeline** — 5-agent LLM pipeline that produces dispatch recommendations
6. **Incident Commander gate** — enforces human-in-the-loop confirmation before any recommendation commits

```
ICP Alpha               ICP Bravo               ICP Charlie ... ICP N
─────────────────────   ─────────────────────   ─────────────────────
Raft Leader             Raft Follower           Raft Follower
  │ AppendEntries RPC──►│                       │
  │◄───────────────────  AppendEntries RPC──────►│
gRPC :50051             gRPC :50052             gRPC :50053
REST :8000              REST :8000              REST :8000
WAL  /data/wal          WAL  /data/wal          WAL  /data/wal
```

The cluster supports an arbitrary number of nodes. A cluster of N nodes can survive the loss of `floor(N/2)` nodes and continue processing writes. Recommended cluster sizes are odd numbers (3, 5, 7) to prevent split votes during elections.

---

## Raft Consensus Implementation

The Raft implementation is a ground-up Python implementation based on the Ongaro & Ousterhout (2014) extended version paper. It covers sections §5.1 through §5.4, §6.4, and §7.

### Safety Invariants

The implementation enforces all five Raft safety invariants:

1. **Election Safety**: At most one leader is elected per term. Enforced by requiring a quorum vote with a single-vote-per-term constraint persisted to the WAL before responding.
2. **Leader Append-Only**: The leader's log is never overwritten. Only followers' conflicting entries are truncated.
3. **Log Matching**: If two log entries share the same index and term, all preceding entries are identical. Enforced by the prev_log_index/prev_log_term consistency check in AppendEntries.
4. **Leader Completeness**: A candidate cannot win an election if its log is less up-to-date than any voter's. Enforced by the `is_up_to_date` check in RequestVote handling.
5. **State Machine Safety**: A log entry is only applied after it is committed (acknowledged by quorum) and applied in monotonically increasing index order.

### Leader Election (§5.2)

Each node starts as a follower with a randomized election timeout between `SALUS_RAFT__ELECTION_TIMEOUT_MIN_MS` and `SALUS_RAFT__ELECTION_TIMEOUT_MAX_MS`. If no AppendEntries heartbeat is received before the timeout expires, the node increments its term, transitions to candidate, votes for itself, and broadcasts RequestVote RPCs to all peers.

A candidate wins if it receives votes from a majority quorum. The leader immediately appends a no-op entry to establish its commit index.

The leader sends periodic AppendEntries heartbeats at `SALUS_RAFT__HEARTBEAT_INTERVAL_MS`. Default is 50ms for a local cluster. For satellite or mesh radio links with higher latency, both the election timeout and heartbeat interval must be raised proportionally.

### Log Replication (§5.3)

The leader appends new entries to its local log and simultaneously replicates them to all followers via AppendEntries RPCs. An entry is committed when the leader has received acknowledgments from a quorum.

AppendEntries are sent in batches of up to `SALUS_RAFT__MAX_APPEND_ENTRIES_BATCH` entries (default: 100) per RPC. If a follower is significantly behind, the leader sends multiple rounds until the follower catches up.

If a follower's `next_index` is behind the leader's log compaction boundary, the leader sends an InstallSnapshot RPC instead.

### Log Compaction and Snapshots (§7)

Once the log exceeds `SALUS_RAFT__MAX_LOG_ENTRIES_BEFORE_COMPACTION` entries, a snapshot of the full state machine is taken. The snapshot is stored in the WAL and all log entries up to the snapshot's `last_included_index` are truncated.

When a follower is too far behind to receive individual AppendEntries, the leader transfers the snapshot via chunked InstallSnapshot RPCs (`SALUS_RAFT__SNAPSHOT_CHUNK_SIZE_BYTES`, default 1MB).

### Persistence (Write-Ahead Log)

The `WALManager` persists Raft state to a SQLite database in WAL journaling mode:

```sql
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
```

Three tables are maintained:

- **`raft_meta`**: `current_term` and `voted_for`. Fsynced before responding to any RPC (§5.2 requirement).
- **`raft_log`**: All log entries with their term, index, command type, and payload.
- **`raft_snapshot`**: The latest state machine snapshot with `last_included_index` and `last_included_term`.

On startup, `WALManager.recover()` returns all persisted state, which `RaftNode.__init__` uses to restore its term, vote, and log before rejoining the cluster.

The WAL database lives at `{SALUS_WAL_DIR}/raft_{node_id}.db`.

---

## Domain State Machine

`DispatchStateMachine` is the Raft application layer. Every committed log entry is applied to this state machine in index order. The state machine is deliberately **pure and deterministic**: no randomness, no wall-clock reads, no external I/O inside `apply()`. Given identical log entry sequences, every node in the cluster produces identical state.

The state machine maintains four in-memory dictionaries:

| Dictionary   | Key    | Value Type      | Description                        |
|--------------|--------|-----------------|------------------------------------|
| `resources`  | str    | `Resource`      | All registered emergency resources |
| `zones`      | str    | `DisasterZone`  | All active disaster zones          |
| `incidents`  | str    | `Incident`      | All reported incidents             |
| `dispatches` | str    | `DispatchOrder` | All dispatch orders                |

Supported command types:

| Command Type                   | Domain Effect                                      |
|--------------------------------|----------------------------------------------------|
| `RESOURCE_REGISTER`            | Add a resource to the cluster inventory            |
| `RESOURCE_DISPATCH`            | Transition resource to `dispatched`, assign zone   |
| `RESOURCE_ARRIVE`              | Mark resource as on-scene                          |
| `RESOURCE_RETURN`              | Return resource to available pool                  |
| `RESOURCE_RESUPPLY_REQUEST`    | Mark resource as awaiting resupply                 |
| `RESOURCE_RESUPPLY_COMPLETE`   | Mark resource as resupplied and available          |
| `RESOURCE_MAINTENANCE`         | Take resource offline for maintenance              |
| `RESOURCE_RESTORE`             | Return resource from maintenance                   |
| `RESOURCE_CANCEL_DISPATCH`     | Cancel an in-flight dispatch                       |
| `ZONE_REGISTER`                | Register a new disaster zone                       |
| `ZONE_UPDATE`                  | Update zone parameters                             |
| `ZONE_PRIORITY_UPDATE`         | Reprioritize a zone                                |
| `INCIDENT_REPORT`              | Report a new incident                              |
| `INCIDENT_UPDATE`              | Update incident status                             |
| `INCIDENT_RESOLVE`             | Mark incident as resolved                          |
| `DISPATCH_ORDER`               | Record a new dispatch order                        |
| `DISPATCH_CONFIRM`             | Record IC confirmation                             |
| `DISPATCH_REJECT`              | Record IC rejection                                |
| `NOOP`                         | Leader commitment confirmation                     |

### Degraded Mode

If a node is partitioned from the cluster quorum, the `GET /api/v1/resources` endpoint marks all resource statuses as `uncertain` and sets `partitioned: true` in the response. This prevents commanders from acting on potentially stale state.

---

## AI Dispatch Pipeline

The AI pipeline is an optional component installed via `pip install 'salus[ai]'`. It is a 5-step sequential chain where each step is an LLM-powered agent independently wrapped in a circuit-breaker. The pipeline always completes and always produces a `DispatchOrder`, even if every LLM agent fails and falls back to rule-based logic.

### Pipeline Stages

**Agent 1: Damage Assessment** (`salus/agents/damage.py`)
Classifies damage severity (1-5), estimates trapped and injured civilian counts, and assigns a dispatch priority. Fallback: scores zone damage based on the stored damage level and applies fixed civilian estimates.

**Agent 2: Resource Matching** (`salus/agents/matcher.py`)
Selects the best-fit resource by matching capabilities against zone needs and considering proximity. Returns recommended resource ID, match score, capability gaps, and alternatives. Fallback: deterministic weighted scoring using capability overlap and Haversine distance.

**Agent 3: Protocol Lookup** (`salus/agents/protocol.py`)
Performs a semantic search against the ChromaDB RAG index. Top-k retrieved chunks are injected into the prompt and the LLM synthesizes a concise protocol recommendation. Fallback: returns a hardcoded rule-based protocol string matched by incident keyword.

**Agent 4: Route Planning** (`salus/agents/router.py`)
Computes straight-line Haversine distance and estimated travel time. Prompts the LLM to augment with context-aware obstacle analysis based on incident type. Fallback: Haversine distance with a generic route description.

**Agent 5: Decision Synthesis** (`salus/agents/decision.py`)
Receives all four prior outputs and produces a `decision_summary` string and a `decision_confidence` float. Confidence is a weighted combination of damage priority, match score, and a per-agent fallback penalty.

### Circuit-Breaker Architecture

Every agent call is wrapped in `with_fallback()` (`salus/agents/circuit_breaker.py`):

```python
result, used_fallback = await with_fallback(
    agent_fn=ai_agent_function,
    fallback_fn=rule_based_function,
    timeout_seconds=config.llm.timeout_seconds,
    agent_name="damage_assessment",
    ...args
)
```

`asyncio.wait_for` races the LLM call against the configured timeout. On `TimeoutError` or any exception, the fallback runs synchronously. The `used_fallback` flag propagates to `DispatchOrder.used_fallback` and applies a confidence penalty in the Decision Synthesis step.

### Supported LLM Providers

| Provider | Variable                       | Default Model        |
|----------|--------------------------------|----------------------|
| `ollama` | (default)                      | `llama3.1:8b`        |
| `google` | `SALUS_LLM__PROVIDER=google`   | `gemini-1.5-flash`   |
| `openai` | `SALUS_LLM__PROVIDER=openai`   | `gpt-4o`             |

### RAG Knowledge Index

`KnowledgeIndex` (`salus/rag/index.py`) wraps ChromaDB with a sentence-transformer embedding model (`all-MiniLM-L6-v2` by default). On startup it ingests:

1. Documents from `data/protocols/` — operator-supplied Markdown protocol files
2. Documents from `data/drugs/` — pharmacological reference documents
3. Auto-generated schema documentation describing all domain models

Chunking uses paragraph-boundary splitting. Each chunk is content-hashed — unchanged documents are never re-embedded on restart. Add `.md` files to `data/protocols/` to make custom protocols available to the Protocol Lookup agent.

---

## Incident Commander Gate

No AI recommendation commits to the Raft log autonomously. After the pipeline produces a `DispatchOrder`, it is placed in the `CommanderGate` with a 120-second expiry.

| Action    | Endpoint                              | Effect                                            |
|-----------|---------------------------------------|---------------------------------------------------|
| Confirm   | `POST /api/v1/dispatch/{id}/confirm`  | Commits `RESOURCE_DISPATCH` to Raft log as-is    |
| Override  | `POST /api/v1/dispatch/{id}/override` | Commits with a different resource selection       |
| Reject    | `POST /api/v1/dispatch/{id}/reject`   | Discards the recommendation — no Raft commit      |

If no action is taken before expiry, `CommanderGate.expire_stale()` auto-rejects the pending confirmation. All Confirm and Override calls require the receiving node to be the current Raft leader. Followers return `409 Conflict` with the known `leader_id` for client redirect.

---

## REST API

| Prefix                  | Description                                       |
|-------------------------|---------------------------------------------------|
| `/api/v1/cluster`       | Raft cluster status, node health                  |
| `/api/v1/resources`     | Resource inventory and registration               |
| `/api/v1/zones`         | Zone registration and priority management         |
| `/api/v1/dispatch`      | Pipeline trigger and IC confirmation gate         |
| `/api/v1/audit`         | Read-only audit log                               |
| `/ws/events`            | WebSocket broadcast of real-time cluster events   |

Interactive API documentation is at `/docs`.

### Key Endpoints

```
GET  /api/v1/cluster/status          Raft node state, term, leader, quorum
GET  /api/v1/resources               All resources (uncertain if partitioned)
POST /api/v1/resources               Register resource (leader; Raft commit)
GET  /api/v1/zones                   All disaster zones
POST /api/v1/zones                   Register zone (leader; Raft commit)
POST /api/v1/dispatch/run-pipeline   Trigger AI pipeline for incident+zone
GET  /api/v1/dispatch/pending        Pending IC confirmations
POST /api/v1/dispatch/{id}/confirm   IC confirms recommendation
POST /api/v1/dispatch/{id}/override  IC overrides resource selection
POST /api/v1/dispatch/{id}/reject    IC rejects recommendation
GET  /api/v1/audit                   Full audit log
```

### WebSocket Events

Connect to `ws://<host>:<port>/ws/events`. Send `ping` to receive `pong` for keepalive.

| Event Type                         | Trigger                                     |
|------------------------------------|---------------------------------------------|
| `resource_registered`              | New resource committed to Raft log          |
| `resource_dispatched`              | IC-confirmed dispatch committed             |
| `dispatch_recommendation_queued`   | AI output queued in Commander Gate          |
| `pipeline_recommendation_ready`    | Full pipeline complete                      |
| `dispatch_rejected`                | IC rejected a recommendation               |

---

## Audit Log

Every AI recommendation, IC decision, resource state transition, and circuit-breaker fallback is recorded in `DispatchAuditLog` (`salus/dispatch/audit.py`). This is an append-only log distinct from the Raft log. The Raft log is the distributed state machine journal; the audit log provides human-readable decision traceability for post-incident analysis.

Audit entries capture: `actor_id`, `actor_type`, `resource_id`, `zone_id`, `incident_id`, `dispatch_id`, `reasoning`, `confidence`, `raft_log_index`, `raft_term`, and whether a commander override occurred.

---

## Configuration

All configuration is driven by environment variables. Nested config uses `__` (double underscore) as the delimiter.

### Node Identity

| Variable              | Default            | Description                    |
|-----------------------|--------------------|--------------------------------|
| `SALUS_NODE_ID`       | `node-1`           | Unique node identifier         |
| `SALUS_ICP_NAME`      | `ICP Alpha`        | Display name                   |
| `SALUS_AGENCY_NAME`   | `Fire Department`  | Operating agency               |
| `SALUS_WAL_DIR`       | `./data/wal`       | Write-ahead log directory      |

### Cluster Membership

```bash
export SALUS_PEERS='[
  {"node_id":"bravo","grpc_address":"icp-bravo:50052"},
  {"node_id":"charlie","grpc_address":"icp-charlie:50053"}
]'
```

### Raft Tuning

| Variable                                        | Default  | Notes                                      |
|-------------------------------------------------|----------|--------------------------------------------|
| `SALUS_RAFT__ELECTION_TIMEOUT_MIN_MS`           | `150`    | Minimum election timeout                   |
| `SALUS_RAFT__ELECTION_TIMEOUT_MAX_MS`           | `300`    | Maximum election timeout                   |
| `SALUS_RAFT__HEARTBEAT_INTERVAL_MS`             | `50`     | Must be << election timeout minimum        |
| `SALUS_RAFT__MAX_LOG_ENTRIES_BEFORE_COMPACTION` | `10000`  | Snapshot trigger threshold                 |
| `SALUS_RAFT__MAX_APPEND_ENTRIES_BATCH`          | `100`    | Max entries per AppendEntries RPC          |

For satellite or mesh radio deployments, increase election timeouts to at least 3x the expected round-trip latency and set heartbeat interval to at most 1/10 of the minimum election timeout.

### LLM Configuration

| Variable                      | Default                    | Notes                            |
|-------------------------------|----------------------------|----------------------------------|
| `SALUS_LLM__PROVIDER`         | `ollama`                   | `ollama`, `google`, or `openai`  |
| `SALUS_LLM__MODEL`            | `llama3.1:8b`              | Model name for chosen provider   |
| `SALUS_LLM__OLLAMA_BASE_URL`  | `http://localhost:11434`   | Ollama server URL                |
| `SALUS_LLM__TIMEOUT_SECONDS`  | `60.0`                     | Per-agent timeout before fallback|
| `SALUS_LLM__TEMPERATURE`      | `0.1`                      | LLM temperature                  |
| `SALUS_LLM__MAX_RETRIES`      | `1`                        | Retries before circuit trips     |

---

## Getting Started

### Single-Node Setup

```bash
git clone https://github.com/SHREEANSH-AGGARWAL/Salus.git
cd Salus
uv sync --extra ai
ollama pull llama3.1:8b
python -m salus.main
```

Server starts at `http://localhost:8000`. Interactive API docs at `http://localhost:8000/docs`.

### Standalone Pipeline Demo

Runs the full AI pipeline without a running cluster. Generates synthetic zones and resources, ingests protocols, and executes a Flash Flood scenario end-to-end.

```bash
python demo.py
```

### Three-Node Docker Cluster

```bash
docker compose up --build
```

| Node    | Agency                | REST API  | gRPC Port |
|---------|-----------------------|-----------|-----------|
| Alpha   | Fire Department       | :8001     | :50051    |
| Bravo   | Emergency Medical     | :8002     | :50052    |
| Charlie | Urban SAR             | :8003     | :50053    |

Each node's WAL is persisted in a named Docker volume. Restarting a container recovers full Raft state from the WAL.

To verify cross-node replication, register a resource on the Alpha leader and read it from Bravo:

```bash
# Register on Alpha (leader on port 8001)
curl -s -X POST http://localhost:8001/api/v1/resources \
  -H "Content-Type: application/json" \
  -d '{"resource": {"id": "r-001", "name": "SAR Team Alpha", ...}}'

# Read from Bravo (follower on port 8002)
curl -s http://localhost:8002/api/v1/resources | jq '.resources[0].name'
```

### Adding Protocol Documents

Place `.md` files in `data/protocols/` before starting the node. The knowledge index ingests them on startup. Files are content-hashed — restarts do not re-embed unchanged documents.

---

## Repository Layout

```
Salus/
├── salus/
│   ├── agents/
│   │   ├── pipeline.py         Pipeline orchestrator (5-agent chain)
│   │   ├── damage.py           Agent 1: Damage Assessment
│   │   ├── matcher.py          Agent 2: Resource Matching
│   │   ├── protocol.py         Agent 3: Protocol Lookup (RAG)
│   │   ├── router.py           Agent 4: Route Planning
│   │   ├── decision.py         Agent 5: Decision Synthesis
│   │   ├── circuit_breaker.py  Timeout + deterministic fallback wrapper
│   │   └── llm.py              LLM provider factory
│   ├── api/
│   │   ├── app.py              FastAPI application factory
│   │   ├── websocket.py        WebSocket broadcaster
│   │   └── routes/             REST route handlers per domain area
│   ├── dispatch/
│   │   ├── state_machine.py    Raft application state machine
│   │   ├── commander_gate.py   IC confirmation gate with TTL expiry
│   │   ├── audit.py            Append-only decision audit log
│   │   ├── matcher.py          Deterministic resource matcher (fallback)
│   │   └── priority.py         Zone prioritization logic
│   ├── models/
│   │   ├── resource.py         Resource, ResourceStatus, state transitions
│   │   ├── zone.py             DisasterZone, ZonePriority
│   │   ├── incident.py         Incident model
│   │   └── dispatch.py         DispatchOrder, DispatchStatus
│   ├── raft/
│   │   ├── node.py             RaftNode (elections, replication, commits)
│   │   ├── log.py              In-memory Raft log with compaction support
│   │   ├── log_entry.py        LogEntry, CommandType enum
│   │   ├── state_machine.py    Abstract StateMachine base class
│   │   └── wal.py              SQLite WAL persistence layer
│   ├── rag/
│   │   ├── index.py            ChromaDB knowledge index
│   │   ├── models.py           RetrievedChunk, IndexStats
│   │   └── schema_docs.py      Auto-generated domain schema documentation
│   ├── transport/
│   │   ├── server.py           gRPC server (RaftServiceServicer)
│   │   ├── client.py           gRPC client pool with connection management
│   │   ├── raft.proto          Protobuf service definition
│   │   ├── raft_pb2.py         Generated protobuf message stubs
│   │   └── raft_pb2_grpc.py    Generated gRPC service stubs
│   ├── config.py               Pydantic Settings for all configuration
│   └── main.py                 Entry point: starts all services
├── simulation/                 Synthetic data generators for testing
├── data/
│   ├── protocols/              Operator Markdown protocol files (RAG source)
│   ├── drugs/                  Pharmacological reference documents (RAG source)
│   └── chroma/                 ChromaDB persistence directory (auto-generated)
├── tests/
│   ├── unit/                   Fast unit tests (no external dependencies)
│   ├── integration/            Multi-node tests (requires Docker cluster)
│   └── chaos/                  Destructive tests (leader death, partition)
├── demo.py                     Standalone end-to-end pipeline demonstration
├── docker-compose.yml          3-node cluster configuration
├── Dockerfile
└── pyproject.toml
```

---

## Development

### Running Tests

```bash
# Unit tests only (fast, no external dependencies)
uv run pytest -m unit

# Integration tests (requires Docker)
docker compose up -d
uv run pytest -m integration

# All tests with coverage
uv run pytest --cov=salus --cov-report=term-missing
```

### Linting and Formatting

```bash
uv run ruff check .
uv run ruff format .
uv run mypy salus/
```

---

## License

MIT — see [LICENSE](LICENSE).
