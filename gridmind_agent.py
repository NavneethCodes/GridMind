#!/usr/bin/env python3
import os, subprocess, json, socket, platform, time, argparse, sys, hashlib

# -------------------- GLOBALS --------------------
GRIDMIND_DIR = os.path.expanduser("~/GridMind")
VENV_DIR = os.path.join(GRIDMIND_DIR, "myenv")
REPORT_PATH = os.path.join(GRIDMIND_DIR, "agent_report.json")
LOG_PATH = os.path.join(GRIDMIND_DIR, "agent_log.txt")
REQUIRED_PY_PKGS = ["psutil", "speedtest-cli", "requests"]
SHARED_SECRET = os.getenv('GRIDMIND_SHARED_SECRET', 'gridmind-dev-secret')


def _canonical_json(payload):
    return json.dumps(payload, sort_keys=True, separators=(',', ':'))


def sign_payload(payload):
    return hashlib.sha256((SHARED_SECRET + _canonical_json(payload)).encode()).hexdigest()

# -------------------- HELPERS --------------------
def log(msg):
    os.makedirs(GRIDMIND_DIR, exist_ok=True)
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")

def sh(cmd, check=True):
    return subprocess.run(cmd, shell=True, check=check, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def zenity_available():
    return subprocess.call("which zenity >/dev/null 2>&1", shell=True) == 0

def zenity_question(title, text):
    if not zenity_available():
        return None
    rc = subprocess.call([
        "zenity", "--question",
        "--title", title,
        "--text", text,
        "--ok-label=Allow", "--cancel-label=Deny"
    ])
    return rc == 0

def zenity_password(prompt):
    if not zenity_available():
        return None
    p = subprocess.run(
        ["zenity", "--password", "--title=GridMind Authentication", "--text", prompt],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )
    return p.stdout.decode().strip()

def notify(title, message):
    if subprocess.call("which notify-send >/dev/null 2>&1", shell=True) == 0:
        subprocess.run(["notify-send", title, message])
    elif zenity_available():
        subprocess.run(["zenity", "--info", "--title", title, "--text", message])
    else:
        log(f"[NOTIFY] {title}: {message}")

# -------------------- SETUP --------------------
def ensure_venv_and_pkgs(password=None):
    try:
        if not os.path.isdir(VENV_DIR):
            sh(f"python3 -m venv {VENV_DIR}")
        pip = os.path.join(VENV_DIR, "bin", "pip")
        sh(f"{pip} install --upgrade pip setuptools wheel")
        sh(f"{pip} install " + " ".join(REQUIRED_PY_PKGS))
    except Exception as e:
        log(f"[!] venv setup failed: {e}")

# -------------------- BENCHMARKS --------------------
def run_sysbench():
    try:
        out = subprocess.getoutput("sysbench cpu --threads=$(nproc) --cpu-max-prime=20000 run")
        for line in out.splitlines():
            line = line.strip().lower()
            if "events per second" in line:
                return line.split(":")[-1].strip()
            if "events/s" in line:
                value = line.split(":")[-1].strip().split("/")[0]
                return value
        return "parse-failed"
    except Exception as e:
        return f"error: {e}"

def run_speedtest():
    python_bin = os.path.join(VENV_DIR, "bin", "python")
    if not os.path.exists(python_bin):
        return 0, 0, "no-venv"
    script = (
        "import speedtest, json; s=speedtest.Speedtest(); s.get_best_server();"
        "print(json.dumps([round(s.download()/1_000_000,2), round(s.upload()/1_000_000,2)]))"
    )
    try:
        out = subprocess.check_output([python_bin, "-c", script], text=True, timeout=120)
        return json.loads(out)[0], json.loads(out)[1], None
    except Exception as e:
        return 0, 0, str(e)


def normalize_report(report):
    """Ensure report has stable numeric/string fields for downstream scoring."""
    network = report.get("network", {}) if isinstance(report.get("network"), dict) else {}

    def _as_float(value, default=0.0):
        try:
            return float(value)
        except Exception:
            return float(default)

    report["cpu_cores"] = int(_as_float(report.get("cpu_cores"), 0))
    report["memory_gb"] = round(_as_float(report.get("memory_gb"), 0.0), 1)
    report["cpu_benchmark"] = str(report.get("cpu_benchmark") or "0 events/sec")
    report["network"] = {
        "download_mbps": round(_as_float(network.get("download_mbps"), 0.0), 2),
        "upload_mbps": round(_as_float(network.get("upload_mbps"), 0.0), 2),
        "error": network.get("error")
    }

    report["hostname"] = str(report.get("hostname") or "unknown")
    report["os"] = str(report.get("os") or "unknown")
    report["cpu_model"] = str(report.get("cpu_model") or "unknown")
    return report

# -------------------- REPORT --------------------
def collect_report():
    import psutil
    report = {
        "hostname": socket.gethostname(),
        "os": platform.system() + " " + platform.release(),
        "cpu_model": subprocess.getoutput("lscpu | grep 'Model name' | awk -F ':' '{print $2}' | xargs"),
        "cpu_cores": psutil.cpu_count(logical=True),
        "memory_gb": round(psutil.virtual_memory().total / (1024 ** 3), 1),
        "cpu_benchmark": f"{run_sysbench()} events/sec",
    }
    dl, ul, err = run_speedtest()
    report["network"] = {"download_mbps": dl, "upload_mbps": ul, "error": err}
    return normalize_report(report)

def post_to_master(url, data):
    python_bin = os.path.join(VENV_DIR, "bin", "python")
    payload = dict(data)
    payload["worker_id"] = get_machine_id()
    payload["timestamp"] = datetime_now_iso()
    payload["checksum"] = sign_payload(payload)
    script = (
        f"import requests, json; d=json.loads('''{json.dumps(payload)}''');"
        f"print(requests.post('{url}', json=d, timeout=10).status_code)"
    )
    for attempt in range(1, 4):
        try:
            subprocess.run([python_bin, "-c", script], check=True)
            return True
        except Exception as e:
            log(f"[!] Post attempt {attempt}/3 failed: {e}")
            if attempt < 3:
                time.sleep(2 * attempt)
    return False


def get_machine_id():
    try:
        with open('/etc/machine-id', 'r') as f:
            return f.read().strip()[:16]
    except Exception:
        return socket.gethostname()


def datetime_now_iso():
    return time.strftime('%Y-%m-%dT%H:%M:%S')

# -------------------- MAIN --------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--master",
        type=str,
        help="Master report endpoint URL (e.g., http://192.168.0.12:5000/report)"
    )
    args = parser.parse_args()

    # If no master specified, try auto-prompt
    if args.master:
        master_url = args.master
    else:
        if zenity_available():
            master_url = subprocess.run(
                ["zenity", "--entry", "--title=GridMind Master", "--text=Enter master report URL:"],
                stdout=subprocess.PIPE
            ).stdout.decode().strip()
        else:
            master_url = input("Enter master report URL (e.g., http://192.168.0.12:5000/report): ").strip()
        if not master_url:
            log("[!] No master URL provided. Exiting.")
            return

    log("[*] GridMind agent started")

    allowed = zenity_question("GridMind Request", "GridMind master requests to run a benchmark on this system. Allow?")
    if allowed is None:
        resp = input("Allow GridMind to run benchmark on this system? (y/N): ").lower()
        allowed = resp == "y"
    if not allowed:
        notify("GridMind", "Benchmark denied by user.")
        return

    pw = zenity_password("Enter your password so GridMind can install required packages.")
    ensure_venv_and_pkgs(pw)

    notify("GridMind", "Running benchmarks...")
    report = collect_report()
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)

    if post_to_master(master_url, report):
        notify("GridMind", "Benchmark complete — results sent.")
    else:
        notify("GridMind", "Benchmark complete — failed to send to master.")

if __name__ == "__main__":
    main()
