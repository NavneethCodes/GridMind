#!/usr/bin/env python3
"""Phase-2 Step 2: ACK + idempotency local validation.

What it validates (offline/local):
1) Master dispatch path works with worker ACK (indirect via job completion)
2) Worker duplicate suppression by message_id (direct socket test)

This script starts master + worker locally, runs checks, writes evidence JSON,
and then stops both processes.
"""

import hashlib
import json
import os
import socket
import subprocess
import time
from urllib import request, parse

ROOT = "/home/navneeth-arun04/GridMind"
MASTER_SCRIPT = f"{ROOT}/master-daemon-rework.py"
WORKER_SCRIPT = f"{ROOT}/worker-listener-daemon.py"
REPORT_PATH = f"{ROOT}/logs/phase2/step2_ack_idempotency_report.json"

MASTER_URL = "http://127.0.0.1:5577"
MASTER_IP = "127.0.0.1"
WORKER_PORT = 5556
SECRET = "gridmind-dev-secret"


def canonical_json(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def sign_payload(payload):
    return hashlib.sha256((SECRET + canonical_json(payload)).encode()).hexdigest()


def post_json(url, payload, timeout=10):
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_json(url, timeout=10):
    with request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def send_command_and_get_ack(command, attempts=12, wait=1.0):
    raw = json.dumps(command).encode("utf-8")
    last_error = None
    for _ in range(attempts):
        try:
            with socket.create_connection((MASTER_IP, WORKER_PORT), timeout=5) as s:
                s.sendall(raw)
                s.shutdown(socket.SHUT_WR)
                ack_raw = s.recv(4096)
            if not ack_raw:
                return None
            return json.loads(ack_raw.decode("utf-8"))
        except Exception as e:
            last_error = str(e)
            time.sleep(wait)
    return {"ack_status": "error", "reason": f"connect-failed: {last_error}"}


def wait_for_workers(timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        data = get_json(f"{MASTER_URL}/api/master/workers")
        workers = (data.get("data") or {}).get("workers") or []
        online = [w for w in workers if w.get("status") == "online"]
        if online:
            return True, data
        time.sleep(1)
    return False, data


def wait_for_job(job_id, timeout=35):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        last = get_json(f"{MASTER_URL}/api/master/job-status?job_id={parse.quote(job_id)}")
        status = (last.get("data") or {}).get("status")
        if status == "completed":
            return True, last
        time.sleep(1)
    return False, last


def main():
    os.makedirs(f"{ROOT}/logs/phase2", exist_ok=True)

    env = os.environ.copy()
    env.update(
        {
            "GRIDMIND_MASTER_IP": MASTER_IP,
            "GRIDMIND_MASTER_PORT": "5577",
            "GRIDMIND_WORKER_COMMAND_PORT": str(WORKER_PORT),
            "GRIDMIND_AUTO_ONBOARD": "true",
            "GRIDMIND_SHARED_SECRET": SECRET,
        }
    )

    # clean old processes (best-effort)
    subprocess.run(["pkill", "-f", "master-daemon-rework.py"], check=False)
    subprocess.run(["pkill", "-f", "worker-listener-daemon.py"], check=False)
    time.sleep(1)

    master_log = open(f"{ROOT}/logs/phase2/step2_master.log", "w")
    worker_log = open(f"{ROOT}/logs/phase2/step2_worker.log", "w")

    master = subprocess.Popen(["python3", MASTER_SCRIPT], env=env, stdout=master_log, stderr=master_log)
    time.sleep(2)
    worker = subprocess.Popen(["python3", WORKER_SCRIPT], env=env, stdout=worker_log, stderr=worker_log)

    report = {
        "step": "phase2-step2",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "checks": {},
    }

    try:
        # Check A: Worker online/discovered
        ok_workers, workers_data = wait_for_workers()
        report["checks"]["worker_online"] = {
            "pass": ok_workers,
            "data": workers_data,
        }

        # Check B: Master dispatch with ACK (indirect via task completion)
        submit = post_json(
            f"{MASTER_URL}/api/master/jobs/submit",
            {
                "job_data": "\n".join(["INFO X", "WARN Y", "ERROR Z", "CRITICAL Q"] * 50),
                "keywords": ["ERROR", "CRITICAL", "WARN"],
            },
        )
        job_id = ((submit.get("data") or {}).get("job_id"))
        ok_job = False
        final_job = None
        if submit.get("status") == "ok" and job_id:
            ok_job, final_job = wait_for_job(job_id)

        report["checks"]["master_dispatch_ack_indirect"] = {
            "pass": bool(ok_job),
            "submit": submit,
            "final_job": final_job,
        }

        # Check C: Duplicate suppression by message_id
        msg_id = f"dup-test-{int(time.time())}"
        command = {
            "action": "run_benchmark",
            "message_id": msg_id,
            "sent_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "benchmark_request_id": f"bench-{int(time.time())}",
            "master_url": f"{MASTER_URL}/api/worker/report",
        }
        command["checksum"] = sign_payload(command)

        ack1 = send_command_and_get_ack(command)
        time.sleep(1)
        ack2 = send_command_and_get_ack(command)

        report["checks"]["duplicate_message_id"] = {
            "pass": bool(ack1 and ack2 and ack1.get("ack_status") == "accepted" and ack2.get("ack_status") == "duplicate"),
            "ack1": ack1,
            "ack2": ack2,
        }

        all_pass = all(v.get("pass") for v in report["checks"].values())
        report["all_pass"] = all_pass
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    finally:
        worker.terminate()
        master.terminate()
        try:
            worker.wait(timeout=5)
        except Exception:
            worker.kill()
        try:
            master.wait(timeout=5)
        except Exception:
            master.kill()

        master_log.close()
        worker_log.close()

    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)

    print(json.dumps(report, indent=2))
    if not report.get("all_pass"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
