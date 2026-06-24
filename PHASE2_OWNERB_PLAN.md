# Phase 2 (Owner B) — Sequential Execution Plan

## Objective

Connectivity, discovery, and transfer reliability hardening in offline-first mode, then LAN validation.

## Step-by-step tasks

1. **Baseline freeze** ✅
   - Snapshot current repo state and config.
   - Artifacts:
     - `logs/phase2/baseline_git_status.txt`
     - `logs/phase2/baseline_env_example.txt`

2. **ACK + idempotency validation** ✅
   - Validate master command ACK handling (`accepted`, `duplicate`, `error`).
   - Validate worker duplicate command suppression by `message_id`.
   - Artifacts:
     - `logs/phase2/step2_ack_idempotency_report.json`
     - `logs/phase2/step2_master.log`
     - `logs/phase2/step2_worker.log`

3. **Offline outbox validation** ⏳
   - Simulate master unreachable.
   - Confirm queueing and later replay/flush on reconnect.

4. **Resumable transfer protocol (offset-based)** ⏳
   - Add `chunk_id`, `offset`, `total_size` handling for resumed sends.

5. **Integrity layer enhancement** ⏳
   - Per-chunk checksum + payload checksum validation and retransmit path.

6. **Adaptive retry policy** ⏳
   - Retry interval tuned by recent failures and RTT.

7. **Connection quality scoring endpoint** ⏳
   - Expose worker link quality (`avg_rtt_ms`, success/failure counts, last error).

8. **Dynamic backpressure tuning** ⏳
   - Auto-adjust per-worker concurrent active task limit by quality score.

9. **Evidence pack + signoff notes** ⏳
   - Logs, pass/fail matrix, known limitations, next actions.

## Rules for this sequence

- Complete one step fully before moving to next.
- Keep changes backward-compatible with current phase-1 behavior.
- Keep all tests executable without router hardware.
