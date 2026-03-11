# Zero Trust Layer 2 Policy Matrix

Version: 1.0.4

## Worker Permission Matrix

Only the following worker-originated permissions are valid:

- `heartbeat` -> `/api/worker/heartbeat`
- `report` -> `/api/worker/report`
- `task-result` -> `/api/worker/task-result`
- `fl-update` -> `/api/worker/fl-update`

Any unknown permission in token payload is rejected.

## Quarantine Policy

- Trust starts at `100`.
- Trust is reduced on auth failures after join is `allowed`.
- Quarantine triggers at or below threshold (`GRIDMIND_TRUST_QUARANTINE_THRESHOLD`).
- Quarantine metadata recorded:
  - `quarantined_at`
  - `quarantine_release_at`
  - `quarantine_reason`
- Cooldown duration is controlled by:
  - `GRIDMIND_TRUST_QUARANTINE_COOLDOWN_SECONDS`

## Recovery Policy

- Unquarantine endpoint: `POST /api/master/worker/unquarantine`
- Default behavior respects cooldown.
- Emergency override: `force=true`
- Operator note can be attached via `note`.

## Validation Script

Use:

- `jobs/phase2_layer2_zero_trust_checks.sh`

This script runs replay/tamper/control checks against the live master API.
