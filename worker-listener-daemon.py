#!/usr/bin/env python3
"""
GridMind Worker Listener Daemon - Lab 1 REWORK
Runs as systemd service on every worker node (even before GridMind files exist)
Listens for master commands to trigger bootstrap and popup
Auto-starts on boot via systemd
"""

import os
import sys
import subprocess
import json
import socket
import time
import logging
import hashlib
import platform
from pathlib import Path
from datetime import datetime
import signal
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler


def _load_env_file(path):
    if not os.path.exists(path):
        return
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass


# Backward compatible env loading (supports running without manual export)
_load_env_file(os.path.expanduser('~/GridMind/.env'))
_load_env_file(os.path.join(os.getcwd(), '.env'))

# Configuration
WORKER_HOME = os.path.expanduser('~')
GRIDMIND_DIR = os.path.join(WORKER_HOME, '.gridmind')
LOG_FILE = os.path.join(GRIDMIND_DIR, 'worker_listener.log')
STATE_FILE = os.path.join(GRIDMIND_DIR, 'listener_state.json')

# Master discovery
MASTER_IP = os.getenv('GRIDMIND_MASTER_IP') or os.getenv('MASTER_NODE_IP', '192.168.0.10')
MASTER_LISTEN_PORT = int(os.getenv('GRIDMIND_MASTER_PORT') or os.getenv('MASTER_LISTEN_PORT', '5577'))  # Port master listens on
WORKER_LISTEN_PORT = int(os.getenv('GRIDMIND_WORKER_COMMAND_PORT') or os.getenv('WORKER_LISTEN_PORT', '5556'))  # Port worker listens on
HEARTBEAT_INTERVAL = int(os.getenv('GRIDMIND_HEARTBEAT_INTERVAL', '10'))
ANNOUNCE_MAX_RETRIES = int(os.getenv('GRIDMIND_ANNOUNCE_MAX_RETRIES', '4'))
SHARED_SECRET = os.getenv('GRIDMIND_SHARED_SECRET', 'gridmind-dev-secret')
OUTBOX_RETRY_BASE_SECONDS = int(os.getenv('GRIDMIND_OUTBOX_RETRY_BASE', '3'))
OUTBOX_RETRY_MAX_SECONDS = int(os.getenv('GRIDMIND_OUTBOX_RETRY_MAX', '60'))
OUTBOX_MAX_RETRY = int(os.getenv('GRIDMIND_OUTBOX_MAX_RETRY', '8'))
REQUIRE_USER_CONSENT = os.getenv('GRIDMIND_REQUIRE_USER_CONSENT', 'true').lower() == 'true'
CONSENT_WEB_PORT = int(os.getenv('GRIDMIND_CONSENT_WEB_PORT', '8765'))
CONSENT_TIMEOUT_SECONDS = int(os.getenv('GRIDMIND_CONSENT_TIMEOUT_SECONDS', '180'))
CONSENT_EVERY_SESSION = os.getenv('GRIDMIND_CONSENT_EVERY_SESSION', 'true').lower() == 'true'
HTTP_REROUTE_ENABLED = os.getenv('GRIDMIND_HTTP_REROUTE_ENABLED', 'true').lower() == 'true'
JOIN_PAGE_AUTO_LAUNCH = os.getenv('GRIDMIND_JOIN_PAGE_AUTO_LAUNCH', 'true').lower() == 'true'
JOIN_PAGE_RELAUNCH_SECONDS = int(os.getenv('GRIDMIND_JOIN_PAGE_RELAUNCH_SECONDS', '20'))

# Ensure directories
Path(GRIDMIND_DIR).mkdir(parents=True, exist_ok=True)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def _canonical_json(payload):
    return json.dumps(payload, sort_keys=True, separators=(',', ':'))


def sign_payload(payload):
    return hashlib.sha256((SHARED_SECRET + _canonical_json(payload)).encode()).hexdigest()


def verify_payload_checksum(payload):
    if not isinstance(payload, dict):
        return False
    incoming = payload.get('checksum')
    if not incoming:
        return False
    payload_copy = dict(payload)
    payload_copy.pop('checksum', None)
    expected = sign_payload(payload_copy)
    return incoming == expected


def run_quick_cpu_benchmark():
    try:
        out = subprocess.getoutput("sysbench cpu --threads=$(nproc) --cpu-max-prime=15000 run")
        for line in out.splitlines():
            low = line.strip().lower()
            if 'events per second' in low:
                return float(low.split(':')[-1].strip())
        return float(os.cpu_count() or 1) * 1000.0
    except Exception:
        return float(os.cpu_count() or 1) * 1000.0


def _consent_page_html(master_ip, master_port):
        return f"""<!doctype html>
<html lang=\"en\">
<head>
    <meta charset=\"UTF-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
    <title>GridMind Join Request</title>
    <style>
        body {{ font-family: Inter, system-ui, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; }}
        .wrap {{ max-width: 700px; margin: 8vh auto; padding: 22px; background: #111827; border: 1px solid #1f2937; border-radius: 12px; }}
        h1 {{ margin-top: 0; }}
        .muted {{ color: #9ca3af; }}
        .row {{ display: flex; gap: 10px; margin-top: 16px; }}
        button {{ border: 0; border-radius: 8px; padding: 10px 16px; font-weight: 700; cursor: pointer; }}
        .ok {{ background: #22c55e; color: #052e16; }}
        .no {{ background: #ef4444; color: #450a0a; }}
        .box {{ margin-top: 12px; background: #0b1220; padding: 10px; border-radius: 8px; border: 1px solid #1f2937; }}
    </style>
</head>
<body>
    <div class=\"wrap\">
        <h1>Join GridMind?</h1>
        <p class=\"muted\">Master <b>{master_ip}:{master_port}</b> requested this device to join the GridMind cluster.</p>
        <div class=\"box\">If you allow, this device can receive benchmark and task commands from the master.</div>
        <form method=\"POST\" action=\"/consent\">
            <div class=\"row\">
                <button class=\"ok\" name=\"decision\" value=\"allow\">Allow</button>
                <button class=\"no\" name=\"decision\" value=\"deny\">Deny</button>
            </div>
        </form>
    </div>
</body>
</html>"""


def _consent_result_html(allowed):
        status = "Allowed" if allowed else "Declined"
        detail = "You can close this tab now."
        color = "#22c55e" if allowed else "#ef4444"
        return f"""<!doctype html><html><head><meta charset=\"UTF-8\"><title>GridMind Decision</title></head>
<body style=\"font-family:Inter,system-ui,sans-serif;background:#0f172a;color:#f8fafc;display:grid;place-items:center;min-height:90vh\">
<div style=\"background:#111827;border:1px solid #1f2937;padding:20px;border-radius:10px;max-width:560px\">
    <h2 style=\"margin-top:0;color:{color}\">{status}</h2>
    <p>{detail}</p>
</div>
</body></html>"""

class WorkerListenerDaemon:
    """Worker daemon that listens for master commands"""
    
    def __init__(self):
        self.worker_id = self.get_machine_id()
        self.mac_address = self.get_mac_address()
        self.hostname = socket.gethostname()
        self.running = True
        self.bootstrap_running = False
        self.pending_outbox = []
        self.processed_message_ids = {}
        self.in_progress_message_ids = set()
        self.link_metrics = {
            'success_count': 0,
            'failure_count': 0,
            'avg_rtt_ms': 0.0,
            'last_error': None,
            'last_success_at': None
        }
        self.user_consent_granted = False
        self.current_join_state = 'pending'
        self.redirect_server = None
        self.redirect_thread = None
        self.command_listener = None
        self.http_redirect_active = False
        self.join_page_launched_for_session = False
        self.last_join_page_launch_ts = 0
        self.task_in_progress = False
        self.shutdown_requested = False
        self.load_state()
        logger.info(f"Worker Listener initialized - ID: {self.worker_id}, MAC: {self.mac_address}")

    def load_state(self):
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, 'r') as f:
                    state = json.load(f)
                self.pending_outbox = state.get('pending_outbox', [])
                self.processed_message_ids = state.get('processed_message_ids', {})
                self.link_metrics = state.get('link_metrics', self.link_metrics)
                self.user_consent_granted = bool(state.get('user_consent_granted', False))
                self.current_join_state = state.get('current_join_state', 'pending')
        except Exception as e:
            logger.warning(f"Could not load listener state: {e}")

    def save_state(self):
        try:
            state = {
                'worker_id': self.worker_id,
                'hostname': self.hostname,
                'pending_outbox': self.pending_outbox,
                # Keep only recent processed IDs to bound file size
                'processed_message_ids': dict(list(self.processed_message_ids.items())[-300:]),
                'link_metrics': self.link_metrics,
                'user_consent_granted': self.user_consent_granted,
                'current_join_state': self.current_join_state,
                'updated_at': datetime.now().isoformat()
            }
            with open(STATE_FILE, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save listener state: {e}")

    def _run_cmd_ok(self, cmd):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            return result.returncode == 0
        except Exception:
            return False

    def start_redirect_server(self):
        if self.redirect_server is not None:
            return True

        daemon_ref = self

        class RedirectHandler(BaseHTTPRequestHandler):
            def do_GET(self_inner):
                target = f"http://{MASTER_IP}:{MASTER_LISTEN_PORT}/join?worker_id={daemon_ref.worker_id}"
                self_inner.send_response(302)
                self_inner.send_header('Location', target)
                self_inner.end_headers()

            def log_message(self_inner, format, *args):
                pass

        try:
            self.redirect_server = HTTPServer(('0.0.0.0', CONSENT_WEB_PORT), RedirectHandler)
            self.redirect_thread = threading.Thread(target=self.redirect_server.serve_forever, daemon=True)
            self.redirect_thread.start()
            return True
        except Exception as e:
            logger.error(f"Redirect server start failed on port {CONSENT_WEB_PORT}: {e}")
            self.redirect_server = None
            self.redirect_thread = None
            return False

    def stop_redirect_server(self):
        if self.redirect_server is None:
            return
        try:
            self.redirect_server.shutdown()
            self.redirect_server.server_close()
        except Exception:
            pass
        self.redirect_server = None
        self.redirect_thread = None

    def set_http_redirect(self, enable):
        if not HTTP_REROUTE_ENABLED:
            return

        # Redirect worker outbound HTTP traffic to local redirect server.
        check_cmd = ['iptables', '-t', 'nat', '-C', 'OUTPUT', '-p', 'tcp', '--dport', '80', '-j', 'REDIRECT', '--to-ports', str(CONSENT_WEB_PORT)]
        add_cmd = ['iptables', '-t', 'nat', '-A', 'OUTPUT', '-p', 'tcp', '--dport', '80', '-j', 'REDIRECT', '--to-ports', str(CONSENT_WEB_PORT)]
        del_cmd = ['iptables', '-t', 'nat', '-D', 'OUTPUT', '-p', 'tcp', '--dport', '80', '-j', 'REDIRECT', '--to-ports', str(CONSENT_WEB_PORT)]

        exists = self._run_cmd_ok(check_cmd)
        if enable:
            if not self.start_redirect_server():
                return
            if not exists:
                if self._run_cmd_ok(add_cmd):
                    self.http_redirect_active = True
                    logger.info("HTTP reroute enabled for join gate")
                else:
                    logger.warning("Could not enable iptables HTTP redirect (run worker with sufficient privileges)")
            else:
                self.http_redirect_active = True
        else:
            if exists:
                self._run_cmd_ok(del_cmd)
            self.http_redirect_active = False

    def fetch_join_state_from_master(self):
        try:
            out = subprocess.check_output([
                'curl', '-sS',
                f'http://{MASTER_IP}:{MASTER_LISTEN_PORT}/api/worker/consent-status?worker_id={self.worker_id}'
            ], text=True, timeout=6)
            data = json.loads(out)
            state = ((data.get('data') or {}).get('join_state')) or 'pending'
            if state not in ('pending', 'allowed', 'denied'):
                return self.current_join_state
            return state
        except Exception:
            # Preserve the last known state on transient API/network failures so
            # we don't flap into pending and reopen join tabs unexpectedly.
            return self.current_join_state

    def launch_join_page(self, force=False):
        if not JOIN_PAGE_AUTO_LAUNCH:
            return

        now = time.time()
        if not force:
            if self.join_page_launched_for_session and (now - self.last_join_page_launch_ts) < JOIN_PAGE_RELAUNCH_SECONDS:
                return

        local_url = f"http://127.0.0.1:{CONSENT_WEB_PORT}/"
        commands = [
            ['xdg-open', local_url],
            ['gio', 'open', local_url],
            ['sensible-browser', local_url],
        ]

        for cmd in commands:
            try:
                proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
                if proc.returncode == 0:
                    self.join_page_launched_for_session = True
                    self.last_join_page_launch_ts = now
                    logger.info(f"Join page launched: {local_url}")
                    return
            except Exception:
                continue

        logger.warning(f"Could not auto-open browser. Open manually on worker: {local_url}")

    def sync_join_gate(self):
        previous_state = self.current_join_state
        state = self.fetch_join_state_from_master()
        self.current_join_state = state

        # Required behavior:
        # - pending => reroute HTTP to master /join
        # - denied  => do not reroute again until reconnect/session reset
        # - allowed => no reroute
        if state == 'pending':
            self.set_http_redirect(True)
            # Auto-open once when entering pending, or once per process startup
            # if we are already pending and no join page has been launched yet.
            if previous_state != 'pending' or not self.join_page_launched_for_session:
                self.launch_join_page(force=True)
        else:
            self.set_http_redirect(False)

        # Ensure score appears promptly right after allow even if benchmark command
        # dispatch is delayed; this reports local benchmark directly to master.
        if state == 'allowed' and previous_state != 'allowed':
            report_url = f'http://{MASTER_IP}:{MASTER_LISTEN_PORT}/api/worker/report'
            self.run_and_send_benchmark(report_url)
        self.save_state()

    def ensure_user_consent(self):
        # Deprecated in HTTP reroute flow; retained for backward compatibility.
        return True

    def _update_link_metrics(self, ok, rtt_ms=None, error=None):
        if ok:
            self.link_metrics['success_count'] = int(self.link_metrics.get('success_count', 0)) + 1
            self.link_metrics['last_success_at'] = datetime.now().isoformat()
            if rtt_ms is not None:
                prev = float(self.link_metrics.get('avg_rtt_ms', 0.0) or 0.0)
                n = max(1, int(self.link_metrics.get('success_count', 1)))
                self.link_metrics['avg_rtt_ms'] = round(((prev * (n - 1)) + rtt_ms) / n, 2)
        else:
            self.link_metrics['failure_count'] = int(self.link_metrics.get('failure_count', 0)) + 1
            self.link_metrics['last_error'] = str(error or 'unknown-error')

    def _post_json_once(self, url, payload, connect_timeout='5', max_time='15', timeout=20):
        start = time.time()
        try:
            response = subprocess.run([
                'curl', '-sS', '-X', 'POST',
                url,
                '-H', 'Content-Type: application/json',
                '-d', json.dumps(payload),
                '--connect-timeout', str(connect_timeout),
                '--max-time', str(max_time)
            ], capture_output=True, text=True, timeout=timeout)

            ok = response.returncode == 0
            rtt_ms = (time.time() - start) * 1000.0
            self._update_link_metrics(ok, rtt_ms=rtt_ms, error=response.stderr.strip())
            return ok, (response.stderr.strip() or response.stdout.strip())
        except Exception as e:
            self._update_link_metrics(False, error=e)
            return False, str(e)

    def enqueue_outbox(self, url, payload, kind):
        item = {
            'id': f"out-{int(time.time() * 1000)}-{len(self.pending_outbox)}",
            'url': url,
            'payload': payload,
            'kind': kind,
            'retry_count': 0,
            'next_retry_at': time.time(),
            'created_at': datetime.now().isoformat()
        }
        self.pending_outbox.append(item)
        self.save_state()

    def post_or_queue(self, url, payload, kind):
        ok, msg = self._post_json_once(url, payload)
        if ok:
            return True
        logger.warning(f"{kind} immediate post failed; queued for retry: {msg}")
        self.enqueue_outbox(url, payload, kind)
        return True

    def flush_outbox(self):
        if not self.pending_outbox:
            return

        now = time.time()
        changed = False
        remaining = []

        for item in self.pending_outbox:
            if item.get('next_retry_at', 0) > now:
                remaining.append(item)
                continue

            ok, msg = self._post_json_once(item['url'], item['payload'])
            if ok:
                changed = True
                continue

            retry_count = int(item.get('retry_count', 0)) + 1
            if retry_count > OUTBOX_MAX_RETRY:
                logger.error(f"Dropping outbox item {item.get('id')} after max retries ({item.get('kind')}): {msg}")
                changed = True
                continue

            backoff = min(OUTBOX_RETRY_BASE_SECONDS * (2 ** (retry_count - 1)), OUTBOX_RETRY_MAX_SECONDS)
            item['retry_count'] = retry_count
            item['next_retry_at'] = now + backoff
            item['last_error'] = msg
            remaining.append(item)
            changed = True

        self.pending_outbox = remaining
        if changed:
            self.save_state()

    def _command_ack(self, status, message_id, reason=None):
        payload = {
            'ack_status': status,
            'message_id': message_id,
            'worker_id': self.worker_id,
            'timestamp': datetime.now().isoformat(),
            'reason': reason
        }
        payload['checksum'] = sign_payload(payload)
        return payload
    
    def get_machine_id(self):
        """Get unique machine identifier"""
        try:
            with open('/etc/machine-id', 'r') as f:
                return f.read().strip()[:16]
        except:
            return socket.gethostname()
    
    def get_mac_address(self):
        """Get MAC address of primary network interface"""
        try:
            result = subprocess.run(
                ['ip', 'link', 'show'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            for line in result.stdout.split('\n'):
                if 'link/ether' in line:
                    return line.split()[1].upper()
            
            return 'unknown'
        except:
            return 'unknown'
    
    def detect_master_presence(self):
        """
        Check if master is reachable.
        Prefer TCP connect to master API port (real service reachability),
        then fall back to ping for environments where port probes fail.
        """
        try:
            sock = socket.create_connection((MASTER_IP, MASTER_LISTEN_PORT), timeout=2)
            sock.close()
            return True
        except Exception:
            try:
                result = subprocess.run(
                    ['ping', '-c', '1', '-W', '2', MASTER_IP],
                    capture_output=True,
                    timeout=5
                )
                return result.returncode == 0
            except Exception:
                return False
    
    def announce_to_master(self):
        """
        Send worker presence announcement to master
        Master listens on MASTER_LISTEN_PORT
        """
        logger.info(f"Announcing presence to master at {MASTER_IP}:{MASTER_LISTEN_PORT}")
        
        announcement = {
            'event': 'worker_discovered',
            'worker_id': self.worker_id,
            'mac_address': self.mac_address,
            'hostname': self.hostname,
            'timestamp': datetime.now().isoformat()
        }
        announcement['checksum'] = sign_payload(announcement)

        backoff = 2
        for attempt in range(1, ANNOUNCE_MAX_RETRIES + 1):
            try:
                result = subprocess.run([
                    'curl', '-sS', '-X', 'POST',
                    f'http://{MASTER_IP}:{MASTER_LISTEN_PORT}/api/worker/announce',
                    '-H', 'Content-Type: application/json',
                    '-d', json.dumps(announcement),
                    '--connect-timeout', '5',
                    '--max-time', '10'
                ], capture_output=True, text=True, timeout=15)

                if result.returncode == 0:
                    logger.info("Announcement sent successfully")
                    return True

                logger.warning(
                    f"Announcement attempt {attempt}/{ANNOUNCE_MAX_RETRIES} failed: {result.stderr.strip() or result.stdout.strip()}"
                )
            except Exception as e:
                logger.warning(f"Announcement attempt {attempt}/{ANNOUNCE_MAX_RETRIES} error: {e}")

            if attempt < ANNOUNCE_MAX_RETRIES:
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)

        return False

    def send_heartbeat(self):
        payload = {
            'event': 'worker_heartbeat',
            'worker_id': self.worker_id,
            'mac_address': self.mac_address,
            'hostname': self.hostname,
            'timestamp': datetime.now().isoformat()
        }
        payload['checksum'] = sign_payload(payload)

        try:
            result = subprocess.run([
                'curl', '-sS', '-X', 'POST',
                f'http://{MASTER_IP}:{MASTER_LISTEN_PORT}/api/worker/heartbeat',
                '-H', 'Content-Type: application/json',
                '-d', json.dumps(payload),
                '--connect-timeout', '3',
                '--max-time', '8'
            ], capture_output=True, text=True, timeout=10)

            if result.returncode != 0:
                logger.debug(f"Heartbeat failed: {result.stderr.strip()}")
                return False
            return True
        except Exception as e:
            logger.debug(f"Heartbeat error: {e}")
            return False

    def send_fl_mock_update(self, round_id):
        """Phase-1 FL scaffold: submit a mock update payload to master."""
        update = {
            'worker_id': self.worker_id,
            'round_id': round_id,
            'update_payload': {
                'samples': 0,
                'avg_loss': 0.0,
                'note': 'phase1-mock-update'
            },
            'timestamp': datetime.now().isoformat()
        }
        update['checksum'] = sign_payload(update)

        return self.post_or_queue(
            f'http://{MASTER_IP}:{MASTER_LISTEN_PORT}/api/worker/fl-update',
            update,
            'fl-update'
        )

    def execute_task(self, command):
        """Phase-1 task executor: keyword counts over chunk text."""
        self.task_in_progress = True
        task_id = command.get('task_id')
        job_id = command.get('job_id')
        chunk_data = str(command.get('chunk_data') or '')
        keywords = command.get('keywords') or ['ERROR', 'CRITICAL', 'WARN']
        master_url = command.get('master_url')
        try:
            if not task_id or not job_id or not master_url:
                logger.warning("Task command missing required fields")
                return False

            text_upper = chunk_data.upper()
            result = {
                'line_count': len([ln for ln in chunk_data.splitlines() if ln.strip()]),
                'keyword_hits': {kw: text_upper.count(str(kw).upper()) for kw in keywords}
            }

            payload = {
                'worker_id': self.worker_id,
                'task_id': task_id,
                'job_id': job_id,
                'result': result,
                'timestamp': datetime.now().isoformat()
            }
            payload['checksum'] = sign_payload(payload)

            ok = self.post_or_queue(master_url, payload, 'task-result')
            if ok:
                logger.info(f"Task {task_id} completed and reported")
            return ok
        finally:
            self.task_in_progress = False
            if self.shutdown_requested:
                self.running = False

    def run_and_send_benchmark(self, master_url):
        memory_gb = 0.0
        try:
            with open('/proc/meminfo', 'r') as f:
                for line in f:
                    if line.startswith('MemTotal:'):
                        kb = float(line.split()[1])
                        memory_gb = round(kb / (1024 * 1024), 1)
                        break
        except Exception:
            memory_gb = 0.0

        report = {
            'worker_id': self.worker_id,
            'hostname': self.hostname,
            'os': platform.system() + ' ' + platform.release(),
            'cpu_model': subprocess.getoutput("lscpu | grep 'Model name' | awk -F ':' '{print $2}' | xargs"),
            'cpu_cores': int(os.cpu_count() or 1),
            'memory_gb': memory_gb,
            'cpu_benchmark': f"{run_quick_cpu_benchmark():.2f} events/sec",
            'network': {
                'download_mbps': 0.0,
                'upload_mbps': 0.0,
                'error': 'worker-listener-quick-benchmark'
            },
            'timestamp': datetime.now().isoformat()
        }
        report['checksum'] = sign_payload(report)

        ok = self.post_or_queue(master_url, report, 'benchmark-report')
        if ok:
            logger.info("Benchmark report posted to master")
        return ok
    
    def wait_for_bootstrap_command(self):
        """
        Listen for bootstrap command from master
        Master will send a command to trigger popup and onboarding
        """
        logger.info(f"Waiting for bootstrap command on port {WORKER_LISTEN_PORT}...")
        
        try:
            import socket as sock

            if self.command_listener is None:
                self.command_listener = sock.socket(sock.AF_INET, sock.SOCK_STREAM)
                self.command_listener.setsockopt(sock.SOL_SOCKET, sock.SO_REUSEADDR, 1)
                self.command_listener.bind(('0.0.0.0', WORKER_LISTEN_PORT))
                self.command_listener.listen(8)

            self.command_listener.settimeout(10)  # short timeout to keep loop responsive

            conn, addr = self.command_listener.accept()
            logger.info(f"Received connection from {addr}")
            
            data = b''
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk

            # Parse command and issue ACK before closing
            command_str = data.decode('utf-8')
            command = json.loads(command_str)
            message_id = command.get('message_id')

            if not message_id:
                ack = self._command_ack('error', None, 'missing message_id')
                conn.sendall(json.dumps(ack).encode('utf-8'))
                conn.close()
                return None

            if not verify_payload_checksum(command):
                ack = self._command_ack('error', message_id, 'invalid checksum')
                conn.sendall(json.dumps(ack).encode('utf-8'))
                conn.close()
                return None

            if message_id in self.processed_message_ids or message_id in self.in_progress_message_ids:
                ack = self._command_ack('duplicate', message_id, 'already processed/in-progress')
                conn.sendall(json.dumps(ack).encode('utf-8'))
                conn.close()
                return None

            self.in_progress_message_ids.add(message_id)
            ack = self._command_ack('accepted', message_id, 'command accepted')
            conn.sendall(json.dumps(ack).encode('utf-8'))

            conn.close()

            logger.info(f"Received command: {command.get('action')} ({message_id})")
            return command
        
        except sock.timeout:
            logger.debug("No bootstrap command received in this interval")
            return None
        except Exception as e:
            logger.error(f"Error waiting for command: {e}")
            if self.command_listener is not None:
                try:
                    self.command_listener.close()
                except Exception:
                    pass
                self.command_listener = None
            return None

    def stop_command_listener(self):
        if self.command_listener is None:
            return
        try:
            self.command_listener.close()
        except Exception:
            pass
        self.command_listener = None
    
    def execute_bootstrap(self, bootstrap_script_path, password):
        """
        Execute the bootstrap script received from master
        with the password from popup
        """
        logger.info(f"Executing bootstrap from {bootstrap_script_path}")
        
        try:
            # Make script executable
            os.chmod(bootstrap_script_path, 0o755)
            
            # Execute bootstrap with password via environment variable
            env = os.environ.copy()
            env['GRIDMIND_PASSWORD'] = password
            
            result = subprocess.run(
                [sys.executable, bootstrap_script_path],
                env=env,
                capture_output=True,
                text=True,
                timeout=300
            )
            
            if result.returncode == 0:
                logger.info("Bootstrap executed successfully")
                self.bootstrap_running = False
                return True
            else:
                logger.error(f"Bootstrap failed: {result.stderr}")
                self.bootstrap_running = False
                return False
        
        except Exception as e:
            logger.error(f"Error executing bootstrap: {e}")
            self.bootstrap_running = False
            return False
    
    def run(self):
        """Main listener loop"""
        logger.info("=" * 60)
        logger.info("GridMind Worker Listener Starting")
        logger.info(f"Worker ID: {self.worker_id}")
        logger.info(f"MAC Address: {self.mac_address}")
        logger.info(f"Listening on port: {WORKER_LISTEN_PORT}")
        logger.info("=" * 60)
        
        # Signal handlers
        signal.signal(signal.SIGTERM, self.shutdown)
        signal.signal(signal.SIGINT, self.shutdown)
        
        retry_interval = 5  # Start with 5 seconds
        max_retry_interval = 320  # Cap at 5+ minutes
        announced = False
        last_heartbeat = 0
        
        while self.running:
            try:
                # Check if master is on network
                if self.shutdown_requested and not self.task_in_progress:
                    self.running = False
                    break

                if self.shutdown_requested and self.task_in_progress:
                    time.sleep(0.5)
                    continue

                master_present = self.detect_master_presence()
                
                if master_present:
                    logger.info("Master detected on network")
                    retry_interval = 5  # Reset retry interval
                    self.flush_outbox()
                    
                    # Announce presence to master
                    if not announced:
                        announced = self.announce_to_master()

                    current_time = time.time()
                    if current_time - last_heartbeat >= HEARTBEAT_INTERVAL:
                        hb_ok = self.send_heartbeat()
                        if hb_ok:
                            last_heartbeat = current_time

                    # HTTP reroute gate state from master join decision
                    if announced:
                        self.sync_join_gate()

                    # Wait for bootstrap/FL command from master
                    command = self.wait_for_bootstrap_command()

                    if command:
                        message_id = command.get('message_id')
                        action = command.get('action')
                        action_ok = False
                        if action == 'trigger_bootstrap':
                            self.bootstrap_running = True
                            bootstrap_path = command.get('bootstrap_script')
                            password = command.get('password')

                            if bootstrap_path and os.path.exists(bootstrap_path):
                                action_ok = self.execute_bootstrap(bootstrap_path, password)
                        elif action == 'fl_round':
                            round_id = command.get('round_id')
                            if round_id:
                                action_ok = self.send_fl_mock_update(round_id)
                        elif action == 'execute_task':
                            action_ok = self.execute_task(command)
                        elif action == 'run_benchmark':
                            master_url = command.get('master_url')
                            if master_url:
                                action_ok = self.run_and_send_benchmark(master_url)
                        elif action == 'terminate_session':
                            logger.info("Safety disconnect received from master; terminating worker session")
                            self.shutdown_requested = True
                            self.running = False
                            action_ok = True

                        if message_id:
                            if action_ok:
                                self.processed_message_ids[message_id] = datetime.now().isoformat()
                            self.in_progress_message_ids.discard(message_id)
                            # keep processed ids bounded
                            if len(self.processed_message_ids) > 500:
                                self.processed_message_ids = dict(list(self.processed_message_ids.items())[-300:])
                            self.save_state()
                else:
                    logger.debug("Master not detected, retrying...")
                    announced = False
                    self.set_http_redirect(False)
                    self.join_page_launched_for_session = False
                    self.last_join_page_launch_ts = 0
                    time.sleep(retry_interval)
                    
                    # Exponential backoff for retries
                    retry_interval = min(retry_interval * 2, max_retry_interval)
            
            except KeyboardInterrupt:
                logger.info("Listener interrupted by user")
                break
            except Exception as e:
                logger.error(f"Listener error: {e}")
                time.sleep(retry_interval)

        self._finalize_shutdown()

    def _finalize_shutdown(self):
        self.set_http_redirect(False)
        self.stop_redirect_server()
        self.stop_command_listener()
        self.save_state()
    
    def shutdown(self, signum=None, frame=None):
        """Graceful shutdown"""
        self.shutdown_requested = True
        if self.task_in_progress:
            logger.info("Shutdown requested; waiting for in-flight task to finish before exit")
            return

        logger.info("Worker Listener shutting down...")
        self._finalize_shutdown()
        self.running = False

if __name__ == '__main__':
    daemon = WorkerListenerDaemon()
    daemon.run()
