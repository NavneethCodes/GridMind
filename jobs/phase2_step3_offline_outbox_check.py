#!/usr/bin/env python3
"""Phase-2 Step 3: Offline outbox validation.

Flow:
1) Start worker with master down.
2) Send signed run_benchmark command directly to worker.
3) Verify worker queues outbound report in local outbox.
4) Start master, wait for worker to reconnect and flush outbox.
5) Verify outbox becomes empty.
"""

import hashlib
import json
import os
import socket
import subprocess
import time

ROOT = "/home/navneeth-arun04/GridMind"
MASTER_SCRIPT = f"{ROOT}/master-daemon-rework.py"
WORKER_SCRIPT = f"{ROOT}/worker-listener-daemon.py"
REPORT_PATH = f"{ROOT}/logs/phase2/step3_offline_outbox_report.json"

MASTER_IP = "127.0.0.1"
MASTER_PORT = 5577
WORKER_PORT = 5556
SECRET = "gridmind-dev-secret"
LISTENER_STATE = os.path.expanduser("~/.gridmind/listener_state.json")


def canonical_json(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def sign_payload(payload):
    return hashlib.sha256((SECRET + canonical_json(payload)).encode()).hexdigest()


def read_listener_state():
    if not os.path.exists(LISTENER_STATE):
        return {}
    with open(LISTENER_STATE, "r") as f:
        return json.load(f)


def send_command_with_retry(command, attempts=20, wait=0.8):
    raw = json.dumps(command).encode("utf-8")
    last = None
    for _ in range(attempts):
        try:
            with socket.create_connection((MASTER_IP, WORKER_PORT), timeout=4) as s:
                s.sendall(raw)
                s.shutdown(socket.SHUT_WR)
                ack = s.recv(4096)
            return json.loads(ack.decode("utf-8")) if ack else None
        except Exception as e:
            last = str(e)
            time.sleep(wait)
    return {"ack_status": "error", "reason": f"connect failed: {last}"}


def wait_for_outbox_size(target, timeout=40):
    end = time.time() + timeout
    last = -1
    while time.time() < end:
        state = read_listener_state()
        outbox = state.get("pending_outbox", [])
        size = len(outbox)
        last = size
        if size == target:
            return True, state
        time.sleep(1)
    return False, read_listener_state() if os.path.exists(LISTENER_STATE) else {"pending_outbox": [{"size": last}]}


def main():
    os.makedirs(f"{ROOT}/logs/phase2", exist_ok=True)

    env = os.environ.copy()
    env.update(
        {
            "GRIDMIND_MASTER_IP": MASTER_IP,
            "GRIDMIND_MASTER_PORT": str(MASTER_PORT),
            "GRIDMIND_WORKER_COMMAND_PORT": str(WORKER_PORT),
            "GRIDMIND_AUTO_ONBOARD": "true",
            "GRIDMIND_SHARED_SECRET": SECRET,
            "GRIDMIND_OUTBOX_RETRY_BASE": "1",
            "GRIDMIND_OUTBOX_RETRY_MAX": "5",
            "GRIDMIND_OUTBOX_MAX_RETRY": "15",
        }
    )

    subprocess.run(["pkill", "-f", "master-daemon-rework.py"], check=False)
    subprocess.run(["pkill", "-f", "worker-listener-daemon.py"], check=False)
    time.sleep(1)

    # Reset listener state for deterministic check
    try:
        if os.path.exists(LISTENER_STATE):
            os.remove(LISTENER_STATE)
    except Exception:
        pass

    worker_log = open(f"{ROOT}/logs/phase2/step3_worker.log", "w")
    master_log = open(f"{ROOT}/logs/phase2/step3_master.log", "w")

    worker = subprocess.Popen(["python3", WORKER_SCRIPT], env=env, stdout=worker_log, stderr=worker_log)
    time.sleep(2)

    report = {
        "step": "phase2-step3",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "checks": {},
    }

    master = None
    try:
        # Master is down now. Send command so worker tries to post benchmark and queues it.
        cmd = {
            "action": "run_benchmark",
            "message_id": f"step3-msg-{int(time.time())}",
            "sent_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "benchmark_request_id": f"bench-{int(time.time())}",
            "master_url": f"http://{MASTER_IP}:{MASTER_PORT}/api/worker/report",
        }
        cmd["checksum"] = sign_payload(cmd)

        ack = send_command_with_retry(cmd)
        report["checks"]["worker_ack"] = {
            "pass": bool(ack and ack.get("ack_status") in ("accepted", "duplicate")),
            "ack": ack,
        }

        queued_ok, queued_state = wait_for_outbox_size(target=1, timeout=30)
        report["checks"]["queued_when_master_down"] = {
            "pass": queued_ok,
            "pending_outbox_size": len((queued_state or {}).get("pending_outbox", [])),
        }

        # Start master and wait for replay/flush
        master = subprocess.Popen(["python3", MASTER_SCRIPT], env=env, stdout=master_log, stderr=master_log)
        time.sleep(3)

        flushed_ok, flushed_state = wait_for_outbox_size(target=0, timeout=60)
        report["checks"]["flushed_after_master_up"] = {
            "pass": flushed_ok,
            "pending_outbox_size": len((flushed_state or {}).get("pending_outbox", [])),
        }

        report["all_pass"] = all(v.get("pass") for v in report["checks"].values())
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    finally:
        worker.terminate()
        if master is not None:
            master.terminate()
        try:
            worker.wait(timeout=5)
        except Exception:
            worker.kill()
        if master is not None:
            try:
                master.wait(timeout=5)
            except Exception:
                master.kill()

        worker_log.close()
        master_log.close()

    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)

    print(json.dumps(report, indent=2))
    if not report.get("all_pass"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
