# GridMind Phase-1 Signoff Checklist

## Goal

Verify that the implemented Phase-1 core path is stable end-to-end:

- worker discovery + heartbeat
- benchmark/scoring ingestion
- job split/assign/result lifecycle
- timeout/requeue behavior
- state persistence and restart safety

## One-command local validation

Use:

- `jobs/phase1_validate_local.sh`

This runs master + worker locally with loopback configuration and executes:

- `jobs/phase1_smoke_test.py`

Pass condition:

- script exits successfully and prints `Phase-1 local validation PASSED`.

## LAN validation (recommended final signoff)

1. Start master with env:
   - `GRIDMIND_MASTER_IP=<master-lan-ip>`
   - `GRIDMIND_MASTER_PORT=5577`
   - `GRIDMIND_AUTO_ONBOARD=true`
2. Start worker on another machine with matching env values.
3. Confirm master logs show announce + heartbeat + online status.
4. Submit a job through `POST /api/master/jobs/submit`.
5. Confirm tasks are assigned and results are received.
6. Confirm `GET /api/master/job-status?job_id=...` reaches `completed`.
7. Stop worker and verify offline transition after timeout.
8. Restart master and verify state is recovered from `master_state.json`.

## Files touched in Phase-1

- `master-daemon-rework.py`
- `worker-listener-daemon.py`
- `gridmind_agent.py`
- `config/phase1_config.json`
- `jobs/phase1_smoke_test.py`
- `jobs/phase1_validate_local.sh`

## Notes

- FL in Phase-1 is scaffolded: round create/update collect/aggregate metadata.
- Full numerical FedAvg for model tensors remains a Phase-2 implementation item.
