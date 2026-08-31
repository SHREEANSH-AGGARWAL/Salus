# Salus — Disaster Response Resource Consensus Network

[![CI](https://github.com/your-org/salus/actions/workflows/ci.yml/badge.svg)](https://github.com/your-org/salus/actions)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

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
# Install
pip install -e ".[dev]"

# Run tests
pytest tests/unit/ -v

# Start 3-ICP cluster
docker-compose up
```

## Project Status

🚧 **Phase 1 — Foundation** (In Progress)

See the [readmes/](readmes/) directory for detailed documentation.

## License

MIT — See [LICENSE](LICENSE)
