# GridMind

GridMind is a LAN-first master/worker orchestration project. It discovers worker machines on the network, asks for user consent, collects benchmark data, schedules chunked jobs, and returns results to the master. The current codebase also includes a Phase-1 federated-learning scaffold and service definitions for running the daemons under systemd.

## Project Summary

This repository is intended to live at the root of the project, with the source files directly inside the top-level `GridMind/` folder. Do not nest another `GridMind/` directory inside it. The local virtual environment folder named `GridMinds/` is not part of the project source and should stay untracked.

## What GridMind Does

- Detects workers on a LAN and verifies signed worker announcements
- Tracks heartbeats and worker liveness
- Supports consent-based onboarding and re-join flow for workers
- Collects CPU, memory, and network benchmark data from worker systems
- Schedules jobs by splitting input text into chunks and assigning tasks to online workers
- Requeues and tracks job/task state through master persistence
- Exposes HTTP endpoints for worker status, job status, and cluster overview
- Provides a Phase-1 federated-learning update path for metadata-only updates

## Main Components

- `master-daemon-rework.py` - master HTTP daemon, worker registry, scheduler, and job state manager
- `worker-listener-daemon.py` - worker-side listener that announces presence, sends heartbeats, handles consent, and executes tasks
- `gridmind_agent.py` - local benchmark and reporting agent used by workers
- `static/dashboard.html` - master dashboard page served by the daemon
- `master-daemon.service` and `worker-listener.service` - systemd unit files
- `jobs/phase1_smoke_test.py` - local API smoke test
- `jobs/phase1_validate_local.sh` - one-command local validation script
- `config/phase1_config.json` - Phase-1 configuration snapshot

## Repository Layout

```text
GridMind/
   README.md
   LICENSE
   .gitignore
   config/
   jobs/
   static/
   master-daemon-rework.py
   worker-listener-daemon.py
   gridmind_agent.py
   master-daemon.service
   worker-listener.service
   PHASE1_SIGNOFF.md
   PHASE2_OWNERB_PLAN.md
```

## How It Works

1. The worker listener starts on a worker machine and announces itself to the master.
2. The master validates the checksum, stores the worker, and marks it online or pending consent.
3. The worker periodically sends heartbeats so the master can maintain liveness.
4. The master can collect benchmark data and use it to influence worker scoring.
5. When a job is submitted, the master splits the input into chunks, creates tasks, and dispatches them to available workers.
6. Workers run the Phase-1 task executor, return results, and the master aggregates completion state.

## Quick Start

1. Create a Python environment and install the runtime dependencies used by the daemons.
2. Configure network settings in `.env` if needed.
3. Start the master daemon.
4. Start one or more worker listener daemons.
5. Run the local validation flow with `jobs/phase1_validate_local.sh`.

## Configuration

The daemons read environment variables from `.env` when present.

Important settings include:

- `GRIDMIND_MASTER_IP` and `GRIDMIND_MASTER_PORT` for the master listener address
- `GRIDMIND_SHARED_SECRET` for payload signing
- `GRIDMIND_AUTO_ONBOARD` to control whether announcements are accepted automatically
- `GRIDMIND_TASK_TIMEOUT` and worker retry settings for scheduling behavior
- `GRIDMIND_FL_ENABLED` for the Phase-1 federated-learning scaffold

## Runtime Artifacts

These files and folders are generated at runtime and should not be committed:

- `logs/`
- `master_logs/`
- `agent_log.txt`
- `agent_report.json`
- `master_state.json`
- `.gridmind/`
- `myenv/`
- `GridMinds/`

## Current Status

- Phase 1 is implemented and has a dedicated signoff checklist in `PHASE1_SIGNOFF.md`
- Phase 2 planning is captured in `PHASE2_OWNERB_PLAN.md`
- The project is best presented on GitHub as a LAN orchestration platform with worker discovery, consent, scheduling, and reporting

## License

MIT License. See `LICENSE`.
