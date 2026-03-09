#!/usr/bin/env python3
"""Owner-B local checks (no router needed).

Prereq: master + one worker already running on localhost with matching env.
"""

import argparse
import json
import time
from urllib import request, parse


def post_json(url, payload):
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_json(url):
    with request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def wait_for_job_completed(master_url, job_id, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        status = get_json(f"{master_url}/api/master/job-status?job_id={parse.quote(job_id)}")
        data = status.get("data") or {}
        if data.get("status") == "completed":
            return True, status
        time.sleep(1)
    return False, status


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--master", default="http://127.0.0.1:5577")
    args = parser.parse_args()

    # 1) Worker visibility
    workers = get_json(f"{args.master}/api/master/workers")
    print("Workers:", workers)
    wdata = workers.get("data") or {}
    if wdata.get("onboarded_count", 0) < 1:
        raise SystemExit("FAIL: no onboarded workers")

    # 2) Submit job large enough to create multiple chunks
    sample = "\n".join([
        "INFO boot",
        "WARN temporary retry",
        "ERROR auth failure",
        "CRITICAL panic detected",
    ] * 80)

    submit = post_json(f"{args.master}/api/master/jobs/submit", {"job_data": sample, "keywords": ["ERROR", "CRITICAL", "WARN"]})
    print("Submit:", submit)
    if submit.get("status") != "ok":
        raise SystemExit("FAIL: job submit failed")

    job_id = submit["data"]["job_id"]

    ok, final_status = wait_for_job_completed(args.master, job_id, timeout=45)
    print("Final job status:", final_status)
    if not ok:
        raise SystemExit("FAIL: job did not complete")

    # 3) Canary should be cleared after first successful task
    workers_after = get_json(f"{args.master}/api/master/workers")
    print("Workers after job:", workers_after)
    any_canary = any(w.get("canary_required") for w in (workers_after.get("data") or {}).get("workers", []))
    if any_canary:
        print("WARN: at least one worker still requires canary (may indicate first task did not complete for that worker).")

    print("PASS: Owner-B local checks completed")


if __name__ == "__main__":
    main()
