# GridMind

GridMind is a LAN-first distributed cybersecurity framework that uses trusted, idle systems to process security logs in parallel.

## Repository Description (for GitHub)

**Distributed cybersecurity grid on LAN with dynamic worker onboarding, benchmark-aware scheduling, fault-tolerant task execution, and federated learning scaffolding.**

## What it does (current)

- Master/worker orchestration with service-ready daemons
- Worker discovery, signed announcements, and heartbeat tracking
- Online/offline liveness reconciliation
- Worker benchmark ingestion and deterministic worker scoring
- Job submission, chunking, assignment, timeout requeue, and result aggregation
- Phase-1 federated learning scaffold (round lifecycle + update collection metadata)

## Core Components

- `master-daemon-rework.py` — Master orchestration server and scheduler
- `worker-listener-daemon.py` — Worker daemon for discovery, command execution, and reporting
- `gridmind_agent.py` — Worker benchmark/report agent
- `master-daemon.service` / `worker-listener.service` — systemd service units
- `jobs/phase1_smoke_test.py` — API-level smoke test
- `jobs/phase1_validate_local.sh` — local Phase-1 validation script

## Quick Start

1. Create and activate Python environment.
2. Start master daemon.
3. Start worker daemon(s).
4. Run Phase-1 validation:
   - `jobs/phase1_validate_local.sh`

## Phase Status

- Phase 1: Implementation complete; runtime signoff checklist available in `PHASE1_SIGNOFF.md`

## Collaborator Tracks

- Collaborator 1: Federated Learning
- Collaborator 2: Connectivity/Zero-Trust/Discovery
- Collaborator 3: Markov-chain scheduling and task split logic

## Suggested Topics for Phase 2

- Full FedAvg tensor aggregation
- Trust-weighted scheduling and aggregation
- Advanced anomaly detection and explainability
- Dashboard and alerting

## License

MIT License (see `LICENSE`).
