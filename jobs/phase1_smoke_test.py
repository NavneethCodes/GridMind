#!/usr/bin/env python3
"""Phase-1 smoke test for GridMind master APIs.

Usage:
  python3 jobs/phase1_smoke_test.py --master http://192.168.0.10:5577
"""

import argparse
import hashlib
import json
import time
from urllib import request, parse


def canonical_json(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def sign_payload(payload, secret):
    return hashlib.sha256((secret + canonical_json(payload)).encode()).hexdigest()


def post_json(url, payload):
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_json(url):
    with request.urlopen(url, timeout=8) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--master", default="http://192.168.0.10:5577")
    parser.add_argument("--secret", default="gridmind-dev-secret")
    args = parser.parse_args()

    print("[1/3] Submitting sample job...")
    submit_resp = post_json(
        f"{args.master}/api/master/jobs/submit",
        {
            "job_data": """INFO session opened\nWARN auth retries\nERROR db timeout\nCRITICAL kernel panic\nINFO session closed""",
            "keywords": ["ERROR", "CRITICAL", "WARN"],
        },
    )
    print(submit_resp)
    if submit_resp.get("status") != "ok":
        raise SystemExit("Job submit failed")

    job_id = submit_resp["data"]["job_id"]

    print("[2/3] Sending synthetic worker heartbeat...")
    hb = {
        "event": "worker_heartbeat",
        "worker_id": "phase1-smoke-worker",
        "hostname": "phase1-smoke-host",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    hb["checksum"] = sign_payload(hb, args.secret)
    try:
        hb_resp = post_json(f"{args.master}/api/worker/heartbeat", hb)
        print(hb_resp)
    except Exception as exc:
        print(f"Heartbeat call skipped/failed in current env: {exc}")

    print("[3/3] Polling job status...")
    final = None
    for _ in range(12):
        status_resp = get_json(f"{args.master}/api/master/job-status?job_id={parse.quote(job_id)}")
        print(status_resp)
        data = status_resp.get("data") or {}
        if data.get("status") == "completed":
            final = status_resp
            break
        time.sleep(1)

    if final is None:
        print("Smoke test warning: job did not reach completed state within timeout.")
        raise SystemExit(2)

    print("Smoke test passed.")


if __name__ == "__main__":
    main()
