#!/usr/bin/env python3
"""
GridMind Master Node Daemon - Lab 1 REWORK
Detects new worker devices, sends bootstrap script, triggers popup remotely
Worker bootstrap runs automatically on worker node via listener daemon
"""

import os
import sys
import subprocess
import json
import time
import logging
import socket
import re
import hashlib
import uuid
import platform
from pathlib import Path
from datetime import datetime
from threading import Thread, Lock
import signal
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse
import base64


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
MASTER_HOME = os.path.expanduser('~')
GRIDMIND_DIR = os.path.join(MASTER_HOME, 'GridMind')
LOG_DIR = os.path.join(GRIDMIND_DIR, 'logs')
STATE_FILE = os.path.join(GRIDMIND_DIR, 'master_state.json')
AUDIT_LOG = os.path.join(LOG_DIR, 'audit.log')
DAEMON_LOG = os.path.join(LOG_DIR, 'master_daemon.log')
BOOTSTRAP_SCRIPT = os.path.join(GRIDMIND_DIR, 'worker-bootstrap.py')
POPUP_SCRIPT = os.path.join(GRIDMIND_DIR, 'gridmind-popup-enhanced.py')
DASHBOARD_HTML = os.path.join(GRIDMIND_DIR, 'static', 'dashboard.html')
PROJECT_VERSION = "1.0.4"

# Network Configuration
ROUTER_GATEWAY = os.getenv('ROUTER_GATEWAY', '192.168.0.1')
MASTER_IP = os.getenv('GRIDMIND_MASTER_IP') or os.getenv('MASTER_NODE_IP', '192.168.0.10')
MASTER_LISTEN_PORT = int(os.getenv('GRIDMIND_MASTER_PORT') or os.getenv('MASTER_LISTEN_PORT', '5577'))
WORKER_IP_START = 11
SCAN_INTERVAL = 5  # seconds
HEARTBEAT_INTERVAL_HINT = int(os.getenv('GRIDMIND_HEARTBEAT_INTERVAL', '10'))
HEARTBEAT_TIMEOUT = int(os.getenv('GRIDMIND_HEARTBEAT_TIMEOUT', '30'))
# Keep timeout above normal heartbeat cadence + command loop jitter.
HEARTBEAT_TIMEOUT = max(HEARTBEAT_TIMEOUT, (HEARTBEAT_INTERVAL_HINT * 2) + 5)
SHARED_SECRET = os.getenv('GRIDMIND_SHARED_SECRET', 'gridmind-dev-secret')
AUTO_ONBOARD_ON_ANNOUNCE = os.getenv('GRIDMIND_AUTO_ONBOARD', 'true').lower() == 'true'
WORKER_COMMAND_PORT = int(os.getenv('GRIDMIND_WORKER_COMMAND_PORT') or os.getenv('WORKER_LISTEN_PORT', '5556'))

# FL (Phase-1 scaffold only)
FL_ENABLED = os.getenv('GRIDMIND_FL_ENABLED', 'true').lower() == 'true'
FL_MIN_CLIENTS = int(os.getenv('GRIDMIND_FL_MIN_CLIENTS', '1'))
FL_ROUND_TIMEOUT = int(os.getenv('GRIDMIND_FL_ROUND_TIMEOUT', '120'))

# Phase-1 scheduler/task settings
TASK_TIMEOUT_SECONDS = int(os.getenv('GRIDMIND_TASK_TIMEOUT', '45'))
CHUNK_MIN_LINES = int(os.getenv('GRIDMIND_CHUNK_MIN_LINES', '10'))
CHUNK_MAX_LINES = int(os.getenv('GRIDMIND_CHUNK_MAX_LINES', '80'))
BENCHMARK_ON_TOPOLOGY_CHANGE = os.getenv('GRIDMIND_BENCHMARK_ON_TOPOLOGY_CHANGE', 'true').lower() == 'true'
BENCHMARK_REDISPATCH_COOLDOWN = int(os.getenv('GRIDMIND_BENCHMARK_REDISPATCH_COOLDOWN', '20'))
MAX_ACTIVE_TASKS_PER_WORKER = int(os.getenv('GRIDMIND_MAX_ACTIVE_TASKS_PER_WORKER', '1'))
CONSENT_EVERY_SESSION = os.getenv('GRIDMIND_CONSENT_EVERY_SESSION', 'true').lower() == 'true'

# Dynamic cluster-share scoring (all active shares sum to 100)
SCORE_CPU_WEIGHT = float(os.getenv('GRIDMIND_SCORE_CPU_WEIGHT', '0.75'))
SCORE_MEM_WEIGHT = float(os.getenv('GRIDMIND_SCORE_MEM_WEIGHT', '0.15'))
SCORE_NET_WEIGHT = float(os.getenv('GRIDMIND_SCORE_NET_WEIGHT', '0.10'))
SCORE_MEM_SCALE = float(os.getenv('GRIDMIND_SCORE_MEM_SCALE', '100.0'))
SCORE_NET_SCALE = float(os.getenv('GRIDMIND_SCORE_NET_SCALE', '10.0'))
SCORE_GAMMA = float(os.getenv('GRIDMIND_SCORE_GAMMA', '1.2'))

# Zero Trust (Layer 1)
ENFORCE_WORKER_TOKENS = os.getenv('GRIDMIND_ENFORCE_WORKER_TOKENS', 'true').lower() == 'true'
WORKER_TOKEN_TTL_SECONDS = int(os.getenv('GRIDMIND_WORKER_TOKEN_TTL_SECONDS', '60'))
WORKER_TOKEN_REFRESH_GRACE_SECONDS = int(os.getenv('GRIDMIND_WORKER_TOKEN_REFRESH_GRACE_SECONDS', '20'))
TOKEN_CLOCK_SKEW_SECONDS = int(os.getenv('GRIDMIND_TOKEN_CLOCK_SKEW_SECONDS', '90'))
REPLAY_WINDOW_SECONDS = int(os.getenv('GRIDMIND_REPLAY_WINDOW_SECONDS', '180'))
TRUST_INITIAL_SCORE = int(os.getenv('GRIDMIND_TRUST_INITIAL_SCORE', '100'))
TRUST_AUTH_FAIL_PENALTY = int(os.getenv('GRIDMIND_TRUST_AUTH_FAIL_PENALTY', '25'))
TRUST_QUARANTINE_THRESHOLD = int(os.getenv('GRIDMIND_TRUST_QUARANTINE_THRESHOLD', '40'))
TRUST_QUARANTINE_COOLDOWN_SECONDS = int(os.getenv('GRIDMIND_TRUST_QUARANTINE_COOLDOWN_SECONDS', '120'))

# Layer 2 policy matrix: only these permissions are valid for worker-originated calls.
WORKER_PERMISSION_SET = {
    'heartbeat',
    'report',
    'task-result',
    'fl-update'
}

# Ensure directories exist
Path(LOG_DIR).mkdir(parents=True, exist_ok=True)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(DAEMON_LOG),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def _canonical_json(payload):
    return json.dumps(payload, sort_keys=True, separators=(',', ':'))


def sign_payload(payload):
    return hashlib.sha256((SHARED_SECRET + _canonical_json(payload)).encode()).hexdigest()


def result_signature(worker_id, task_id, result_hash):
    return hashlib.sha256((SHARED_SECRET + str(worker_id) + str(task_id) + str(result_hash)).encode('utf-8')).hexdigest()


def verify_payload_checksum(payload):
    if not isinstance(payload, dict):
        return False
    incoming = payload.get('checksum')
    if not incoming:
        return False
    payload_copy = dict(payload)
    payload_copy.pop('checksum', None)
    # Transport metadata added by master should not be part of sender signature.
    payload_copy.pop('master_observed_ip', None)
    expected = sign_payload(payload_copy)
    return incoming == expected

class AuditLogger:
    """Separate audit logger"""
    def __init__(self):
        self.audit_handler = logging.FileHandler(AUDIT_LOG)
        self.audit_handler.setFormatter(
            logging.Formatter('%(asctime)s | %(message)s')
        )
        self.audit_logger = logging.getLogger('audit')
        self.audit_logger.setLevel(logging.INFO)
        self.audit_logger.addHandler(self.audit_handler)
    
    def log(self, event_type, worker_id, details):
        self.audit_logger.info(f"{event_type} | {worker_id} | {details}")

class WorkerAnnounceHandler(BaseHTTPRequestHandler):
    """HTTP handler for worker announcements"""
    
    master_daemon = None  # Will be set by master

    def _read_json_body(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        return json.loads(body.decode('utf-8'))

    def _send_json(self, status_code, payload):
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def _send_html(self, status_code, html):
        self.send_response(status_code)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))

    def _join_page_html(self, worker_id, state):
        state_text = state or 'pending'
        if state_text == 'allowed':
            actions_html = """
<div class=\"row\"> 
<button class=\"ok\" name=\"decision\" value=\"allow\">Keep Joined</button>
<button class=\"no\" name=\"decision\" value=\"leave\">Leave GridMind</button>
</div>"""
        else:
            actions_html = """
<div class=\"row\"> 
<button class=\"ok\" name=\"decision\" value=\"allow\">Allow</button>
<button class=\"no\" name=\"decision\" value=\"deny\">Deny</button>
</div>"""
        return f"""<!doctype html>
<html lang=\"en\"><head><meta charset=\"UTF-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
<title>Join GridMind</title>
<style>
body {{ font-family: Inter, system-ui, sans-serif; background:#0f172a; color:#f8fafc; margin:0; display:grid; place-items:center; min-height:100vh; }}
.card {{ width:min(680px,94vw); background:#111827; border:1px solid #1f2937; border-radius:12px; padding:22px; }}
h1 {{ margin-top:0; }}
.muted {{ color:#9ca3af; }}
.row {{ display:flex; gap:10px; margin-top:16px; }}
button {{ border:0; border-radius:8px; padding:10px 16px; font-weight:700; cursor:pointer; }}
.ok {{ background:#22c55e; color:#052e16; }}
.no {{ background:#ef4444; color:#450a0a; }}
</style></head>
<body><div class=\"card\">
<h1>Join GridMind</h1>
<p class=\"muted\">Worker ID: <b>{worker_id or 'unknown'}</b></p>
<p class=\"muted\">Current state: <b>{state_text}</b></p>
<p>This device can participate in distributed log analysis for this session.</p>
<form method=\"POST\" action=\"/join\">
<input type=\"hidden\" name=\"worker_id\" value=\"{worker_id or ''}\" />
{actions_html}
</form>
</div></body></html>"""

    def _join_result_html(self, allowed, worker_id=None):
        status = 'Joined GridMind' if allowed else 'Declined GridMind'
        color = '#22c55e' if allowed else '#ef4444'
        leave_form = ''
        if allowed:
            leave_form = f"""
<form method=\"POST\" action=\"/join\" style=\"margin-top:12px\">
<input type=\"hidden\" name=\"worker_id\" value=\"{worker_id or ''}\" />
<button style=\"border:0;border-radius:8px;padding:10px 16px;font-weight:700;cursor:pointer;background:#ef4444;color:#450a0a\" name=\"decision\" value=\"leave\">Leave GridMind</button>
</form>"""
        return f"""<!doctype html><html><head><meta charset=\"UTF-8\"><title>GridMind Join</title></head>
<body style=\"font-family:Inter,system-ui,sans-serif;background:#0f172a;color:#f8fafc;display:grid;place-items:center;min-height:100vh\">
<div style=\"background:#111827;border:1px solid #1f2937;padding:20px;border-radius:10px;max-width:560px\">
<h2 style=\"margin-top:0;color:{color}\">{status}</h2>
<p>Your choice has been saved for this connection session.</p>
{leave_form}
</div>
</body></html>"""

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ('/', '/dashboard'):
            try:
                with open(DASHBOARD_HTML, 'r', encoding='utf-8') as f:
                    html = f.read()
                self._send_html(200, html)
            except Exception as e:
                self._send_html(500, f"<h1>Dashboard unavailable</h1><p>{e}</p>")
        elif parsed.path == '/join':
            if not self.master_daemon:
                self._send_html(503, '<h1>Master unavailable</h1>')
                return
            query = urllib.parse.parse_qs(parsed.query)
            worker_id = (query.get('worker_id') or [None])[0]
            if not worker_id:
                worker_id = self.master_daemon.resolve_worker_id_by_ip(self.client_address[0])
            state = self.master_daemon.get_worker_join_state(worker_id)
            self._send_html(200, self._join_page_html(worker_id, state))
        elif parsed.path == '/api/master/job-status':
            query = urllib.parse.parse_qs(parsed.query)
            job_id = (query.get('job_id') or [None])[0]

            if not self.master_daemon:
                self._send_json(503, {'status': 'error', 'reason': 'master unavailable'})
                return

            ok, data, reason = self.master_daemon.get_job_status(job_id)
            self._send_json(200 if ok else 404, {'status': 'ok' if ok else 'error', 'reason': reason, 'data': data})
        elif parsed.path == '/api/master/workers':
            if not self.master_daemon:
                self._send_json(503, {'status': 'error', 'reason': 'master unavailable'})
                return
            ok, data, reason = self.master_daemon.get_workers_status()
            self._send_json(200 if ok else 400, {'status': 'ok' if ok else 'error', 'reason': reason, 'data': data})
        elif parsed.path == '/api/master/overview':
            if not self.master_daemon:
                self._send_json(503, {'status': 'error', 'reason': 'master unavailable'})
                return
            ok, data, reason = self.master_daemon.get_cluster_overview()
            self._send_json(200 if ok else 400, {'status': 'ok' if ok else 'error', 'reason': reason, 'data': data})
        elif parsed.path == '/api/worker/consent-status':
            if not self.master_daemon:
                self._send_json(503, {'status': 'error', 'reason': 'master unavailable'})
                return
            query = urllib.parse.parse_qs(parsed.query)
            worker_id = (query.get('worker_id') or [None])[0]
            if not worker_id:
                worker_id = self.master_daemon.resolve_worker_id_by_ip(self.client_address[0])
            state = self.master_daemon.get_worker_join_state(worker_id)
            self._send_json(200, {'status': 'ok', 'reason': 'ok', 'data': {'worker_id': worker_id, 'join_state': state}})
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_POST(self):
        """Handle worker API requests"""
        if self.path == '/api/worker/announce':
            try:
                announcement = self._read_json_body()
                announcement['master_observed_ip'] = self.client_address[0]
                logger.info(f"Received announcement from {announcement.get('hostname')}")
                
                # Pass to master daemon
                if self.master_daemon:
                    ok, reason = self.master_daemon.handle_worker_announcement(announcement)
                else:
                    ok, reason = False, 'master unavailable'
                
                token_data = None
                if ok and self.master_daemon:
                    tok_ok, token, token_exp, tok_reason = self.master_daemon.issue_worker_token(announcement.get('worker_id'))
                    if tok_ok:
                        token_data = {'auth_token': token, 'token_expires_at_epoch': token_exp}
                    else:
                        reason = f"{reason}; token issue failed: {tok_reason}"

                # Send response
                self._send_json(
                    200 if ok else 400,
                    {'status': 'ok' if ok else 'error', 'reason': reason, 'data': token_data}
                )
            
            except Exception as e:
                logger.error(f"Error handling announcement: {e}")
                self.send_response(400)
                self.end_headers()
        elif self.path == '/api/worker/heartbeat':
            try:
                heartbeat = self._read_json_body()
                heartbeat['master_observed_ip'] = self.client_address[0]

                if self.master_daemon:
                    ok_auth, auth_reason = self.master_daemon._enforce_worker_request_or_penalize(heartbeat, 'heartbeat')
                    if not ok_auth:
                        self._send_json(401, {'status': 'error', 'reason': auth_reason})
                        return
                    ok, reason = self.master_daemon.handle_worker_heartbeat(heartbeat)
                else:
                    ok, reason = False, 'master unavailable'

                self._send_json(200 if ok else 400, {'status': 'ok' if ok else 'error', 'reason': reason})

            except Exception as e:
                logger.error(f"Error handling heartbeat: {e}")
                self.send_response(400)
                self.end_headers()
        elif self.path == '/api/worker/fl-update':
            try:
                update = self._read_json_body()
                if self.master_daemon:
                    ok_auth, auth_reason = self.master_daemon._enforce_worker_request_or_penalize(update, 'fl-update')
                    if not ok_auth:
                        self._send_json(401, {'status': 'error', 'reason': auth_reason})
                        return
                    ok, reason = self.master_daemon.collect_fl_update(update)
                else:
                    ok, reason = False, 'master unavailable'

                self._send_json(200 if ok else 400, {'status': 'ok' if ok else 'error', 'reason': reason})

            except Exception as e:
                logger.error(f"Error handling FL update: {e}")
                self.send_response(400)
                self.end_headers()
        elif self.path == '/api/worker/report':
            try:
                report = self._read_json_body()
                report['master_observed_ip'] = self.client_address[0]

                if self.master_daemon:
                    ok_auth, auth_reason = self.master_daemon._enforce_worker_request_or_penalize(report, 'report')
                    if not ok_auth:
                        self._send_json(401, {'status': 'error', 'reason': auth_reason})
                        return
                    ok, reason = self.master_daemon.handle_worker_report(report)
                else:
                    ok, reason = False, 'master unavailable'

                self._send_json(200 if ok else 400, {'status': 'ok' if ok else 'error', 'reason': reason})
            except Exception as e:
                logger.error(f"Error handling worker report: {e}")
                self.send_response(400)
                self.end_headers()
        elif self.path == '/api/master/jobs/submit':
            try:
                payload = self._read_json_body()

                if self.master_daemon:
                    ok, data, reason = self.master_daemon.submit_job(payload)
                else:
                    ok, data, reason = False, None, 'master unavailable'

                self._send_json(
                    200 if ok else 400,
                    {'status': 'ok' if ok else 'error', 'reason': reason, 'data': data}
                )
            except Exception as e:
                logger.error(f"Error submitting job: {e}")
                self.send_response(400)
                self.end_headers()
        elif self.path == '/api/worker/task-result':
            try:
                payload = self._read_json_body()
                if self.master_daemon:
                    ok_auth, auth_reason = self.master_daemon._enforce_worker_request_or_penalize(payload, 'task-result')
                    if not ok_auth:
                        self._send_json(401, {'status': 'error', 'reason': auth_reason})
                        return
                    ok, reason = self.master_daemon.handle_task_result(payload)
                else:
                    ok, reason = False, 'master unavailable'

                self._send_json(200 if ok else 400, {'status': 'ok' if ok else 'error', 'reason': reason})
            except Exception as e:
                logger.error(f"Error handling task result: {e}")
                self.send_response(400)
                self.end_headers()
        elif self.path == '/api/master/benchmarks/refresh':
            try:
                if self.master_daemon:
                    ok, data, reason = self.master_daemon.refresh_benchmarks_now()
                else:
                    ok, data, reason = False, None, 'master unavailable'

                self._send_json(
                    200 if ok else 400,
                    {'status': 'ok' if ok else 'error', 'reason': reason, 'data': data}
                )
            except Exception as e:
                logger.error(f"Error refreshing benchmarks: {e}")
                self.send_response(400)
                self.end_headers()
        elif self.path == '/api/master/worker/disconnect':
            try:
                payload = self._read_json_body()
                worker_id = payload.get('worker_id')

                if self.master_daemon:
                    ok, reason = self.master_daemon.safety_disconnect_worker(worker_id)
                else:
                    ok, reason = False, 'master unavailable'

                self._send_json(200 if ok else 400, {
                    'status': 'ok' if ok else 'error',
                    'reason': reason,
                    'data': {'worker_id': worker_id}
                })
            except Exception as e:
                logger.error(f"Error disconnecting worker: {e}")
                self.send_response(400)
                self.end_headers()
        elif self.path == '/api/master/worker/unquarantine':
            try:
                payload = self._read_json_body()
                worker_id = payload.get('worker_id')
                force = bool(payload.get('force', False))
                note = payload.get('note')

                if self.master_daemon:
                    ok, reason = self.master_daemon.unquarantine_worker_with_policy(worker_id, force=force, note=note)
                else:
                    ok, reason = False, 'master unavailable'

                self._send_json(200 if ok else 400, {
                    'status': 'ok' if ok else 'error',
                    'reason': reason,
                    'data': {'worker_id': worker_id, 'force': force}
                })
            except Exception as e:
                logger.error(f"Error unquarantining worker: {e}")
                self.send_response(400)
                self.end_headers()
        elif self.path == '/api/worker/token/refresh':
            try:
                payload = self._read_json_body()
                worker_id = payload.get('worker_id')
                if not worker_id:
                    self._send_json(400, {'status': 'error', 'reason': 'worker_id is required'})
                    return

                ok_fields, reason_fields = self.master_daemon._validate_required_fields(
                    payload,
                    ['worker_id', 'timestamp', 'message_id', 'checksum']
                )
                if not ok_fields:
                    self._send_json(400, {'status': 'error', 'reason': reason_fields})
                    return
                if not verify_payload_checksum(payload):
                    self._send_json(401, {'status': 'error', 'reason': 'invalid checksum'})
                    return

                if self.master_daemon:
                    ok, token, token_exp, reason = self.master_daemon.issue_worker_token(worker_id)
                else:
                    ok, token, token_exp, reason = False, None, None, 'master unavailable'

                self._send_json(
                    200 if ok else 400,
                    {
                        'status': 'ok' if ok else 'error',
                        'reason': reason,
                        'data': {'auth_token': token, 'token_expires_at_epoch': token_exp} if ok else None
                    }
                )
            except Exception as e:
                logger.error(f"Error refreshing worker token: {e}")
                self.send_response(400)
                self.end_headers()
        elif self.path == '/join':
            if not self.master_daemon:
                self._send_html(503, '<h1>Master unavailable</h1>')
                return
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                raw = self.rfile.read(content_length).decode('utf-8')
                params = urllib.parse.parse_qs(raw)
                worker_id = (params.get('worker_id') or [None])[0]
                decision = str((params.get('decision') or ['deny'])[0]).strip().lower()

                if not worker_id:
                    worker_id = self.master_daemon.resolve_worker_id_by_ip(self.client_address[0])

                normalized = 'deny' if decision == 'leave' else decision
                allowed = (normalized == 'allow')
                ok, reason = self.master_daemon.set_worker_join_state(worker_id, 'allowed' if allowed else 'denied')

                # Join pages can be opened with stale worker_id values in edge cases
                # (cached tabs / old redirects). Retry once by requester IP.
                if (not ok) and reason in ('worker not onboarded', 'worker_id not found for requester IP'):
                    resolved_worker_id = self.master_daemon.resolve_worker_id_by_ip(self.client_address[0])
                    if resolved_worker_id and resolved_worker_id != worker_id:
                        ok, reason = self.master_daemon.set_worker_join_state(
                            resolved_worker_id,
                            'allowed' if allowed else 'denied'
                        )
                        worker_id = resolved_worker_id

                if not ok:
                    self._send_html(400, f"<h1>Join update failed</h1><p>{reason}</p>")
                    return
                self._send_html(200, self._join_result_html(allowed, worker_id=worker_id))
            except Exception as e:
                logger.error(f"Error handling join decision: {e}")
                self.send_response(400)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        """Suppress default logging"""
        pass

class MasterDaemon:
    """Master daemon for GridMind orchestration"""
    
    def __init__(self):
        self.master_id = self.get_machine_id()
        self.master_hostname = socket.gethostname()
        self.started_at = datetime.now().isoformat()
        self.detected_workers = {}  # MAC -> worker info
        self.onboarded_workers = {}  # worker_id -> worker info
        self.worker_lock = Lock()
        self.next_worker_ip = WORKER_IP_START
        self.audit = AuditLogger()
        self.running = True
        self.fl_round_state = {
            'current_round': None,
            'rounds': {}
        }
        self.task_state = {
            'jobs': {},
            'pending_tasks': [],
            'active_tasks': {},
            'completed_tasks': {}
        }
        self.topology_dirty = True
        self.last_benchmark_dispatch_at = 0
        self.master_benchmark_report = {}
        self.master_cpu_prev_total = None
        self.master_cpu_prev_idle = None
        self.replay_guard = {}
        self.load_state()
        self.collect_master_benchmark()
        self._read_local_cpu_usage_percent()
        self.reset_worker_trust_for_new_session()
        logger.info(f"GridMind Master Daemon initialized - ID: {self.master_id}")

    def reset_worker_trust_for_new_session(self):
        """High-priority policy: every worker is unknown at session start.

        This intentionally drops remembered approvals so reconnect/start always begins
        at join_state=pending for all non-master workers.
        """
        with self.worker_lock:
            changed = False
            # Safety: master must never appear as a worker card.
            if self.master_id in self.onboarded_workers:
                del self.onboarded_workers[self.master_id]
                changed = True
            for worker_id, worker in self.onboarded_workers.items():
                # master_id is not a worker record, but keep guard for future-proofing.
                if worker_id == self.master_id:
                    continue
                if worker.get('join_state') != 'pending':
                    worker['join_state'] = 'pending'
                    changed = True
                if worker.get('status') != 'disconnected':
                    worker['status'] = 'disconnected'
                    changed = True
            if changed:
                self.save_state()

    def _validate_required_fields(self, payload, required_fields):
        missing = [k for k in required_fields if not payload.get(k)]
        if missing:
            return False, f"Missing required fields: {', '.join(missing)}"
        return True, None

    def _utc_now_epoch(self):
        return int(time.time())

    def _encode_token(self, token_payload):
        token_json = json.dumps(token_payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
        token_b64 = base64.urlsafe_b64encode(token_json).decode('ascii').rstrip('=')
        signature = hashlib.sha256((SHARED_SECRET + token_b64).encode('utf-8')).hexdigest()
        return f"{token_b64}.{signature}"

    def _decode_token(self, token):
        if not token or '.' not in token:
            return False, None, 'missing or malformed token'
        try:
            token_b64, signature = token.rsplit('.', 1)
            expected = hashlib.sha256((SHARED_SECRET + token_b64).encode('utf-8')).hexdigest()
            if signature != expected:
                return False, None, 'token signature invalid'

            padded = token_b64 + '=' * (-len(token_b64) % 4)
            payload_raw = base64.urlsafe_b64decode(padded.encode('ascii')).decode('utf-8')
            payload = json.loads(payload_raw)
            return True, payload, 'ok'
        except Exception:
            return False, None, 'token decode failed'

    def _issue_worker_token_locked(self, worker):
        now = self._utc_now_epoch()
        worker_id = worker.get('worker_id')
        token_payload = {
            'node_id': worker_id,
            'issued_at': now,
            'expires_at': now + WORKER_TOKEN_TTL_SECONDS,
            'permissions': ['heartbeat', 'report', 'task-result', 'fl-update'],
            'node_hash': hashlib.sha256(f"{worker.get('mac', '')}:{worker_id}".encode('utf-8')).hexdigest(),
            'jti': f"tok-{uuid.uuid4().hex[:16]}"
        }
        token = self._encode_token(token_payload)
        worker['session_token'] = token
        worker['session_token_expires_at'] = datetime.fromtimestamp(token_payload['expires_at']).isoformat()
        worker['session_token_issued_at'] = datetime.fromtimestamp(token_payload['issued_at']).isoformat()
        worker['session_token_jti'] = token_payload['jti']
        worker['token_revoked'] = False
        return token, token_payload['expires_at']

    def _find_worker_by_id_locked(self, worker_id):
        if not worker_id:
            return None
        if worker_id in self.onboarded_workers:
            return self.onboarded_workers.get(worker_id)
        for _, worker in self.onboarded_workers.items():
            if worker.get('worker_id') == worker_id:
                return worker
        return None

    def _adjust_worker_trust_locked(self, worker, delta, reason):
        current = int(worker.get('trust_score', TRUST_INITIAL_SCORE))
        updated = max(0, min(100, current + int(delta)))
        worker['trust_score'] = updated
        worker['trust_updated_at'] = datetime.now().isoformat()
        if updated <= TRUST_QUARANTINE_THRESHOLD:
            worker['quarantined'] = True
            worker['quarantine_reason'] = reason
            worker['quarantined_at'] = datetime.now().isoformat()
            worker['quarantine_release_at'] = datetime.fromtimestamp(
                self._utc_now_epoch() + TRUST_QUARANTINE_COOLDOWN_SECONDS
            ).isoformat()
        self.audit.log('TRUST', worker.get('worker_id'), f"score={updated} delta={delta} reason={reason}")

    def issue_worker_token(self, worker_id):
        with self.worker_lock:
            worker = self._find_worker_by_id_locked(worker_id)
            if not worker:
                return False, None, None, 'worker not onboarded'
            if worker.get('quarantined'):
                return False, None, None, 'worker quarantined'
            token, expires_at_epoch = self._issue_worker_token_locked(worker)
            self.save_state()
        return True, token, expires_at_epoch, 'token issued'

    def _cleanup_replay_guard(self):
        now = self._utc_now_epoch()
        stale = [mid for mid, seen_at in self.replay_guard.items() if (now - int(seen_at)) > REPLAY_WINDOW_SECONDS]
        for mid in stale:
            self.replay_guard.pop(mid, None)

    def _verify_worker_request(self, payload, required_permission):
        if not ENFORCE_WORKER_TOKENS:
            return True, None, 'ok'

        if required_permission not in WORKER_PERMISSION_SET:
            return False, None, f'unknown permission mapping: {required_permission}'

        worker_id = payload.get('worker_id')
        if not worker_id:
            return False, None, 'missing worker_id'

        # Zero-trust enforcement starts only after explicit allow.
        # Pending/denied workers may still send announce/heartbeat during join flow.
        with self.worker_lock:
            worker = self._find_worker_by_id_locked(worker_id)
            if not worker:
                return False, None, 'worker not onboarded'
            if worker.get('join_state', 'pending') != 'allowed':
                return True, None, 'pre-join auth bypass'

        message_id = payload.get('message_id')
        if not message_id:
            return False, None, 'missing message_id'

        timestamp_raw = payload.get('timestamp')
        if not timestamp_raw:
            return False, None, 'missing timestamp'

        try:
            payload_ts = int(datetime.fromisoformat(str(timestamp_raw)).timestamp())
        except Exception:
            return False, None, 'invalid timestamp format'

        now = self._utc_now_epoch()
        if abs(now - payload_ts) > TOKEN_CLOCK_SKEW_SECONDS:
            return False, None, 'timestamp outside allowed skew'

        token = payload.get('auth_token')
        ok_tok, tok_payload, tok_reason = self._decode_token(token)
        if not ok_tok:
            return False, None, tok_reason

        if tok_payload.get('node_id') != worker_id:
            return False, None, 'token node mismatch'

        perms = tok_payload.get('permissions') or []
        for perm in perms:
            if perm not in WORKER_PERMISSION_SET:
                return False, None, 'token contains unsupported permission'
        if required_permission not in perms:
            return False, None, 'token permission denied'

        exp = int(tok_payload.get('expires_at') or 0)
        iat = int(tok_payload.get('issued_at') or 0)
        if now < (iat - TOKEN_CLOCK_SKEW_SECONDS):
            return False, None, 'token not yet valid'
        if now > exp:
            return False, None, 'token expired'

        with self.worker_lock:
            worker = self._find_worker_by_id_locked(worker_id)
            if worker.get('quarantined'):
                release_at_str = worker.get('quarantine_release_at')
                if release_at_str:
                    return False, worker, f"worker quarantined until {release_at_str}"
                return False, worker, 'worker quarantined'

            if worker.get('token_revoked'):
                return False, worker, 'token revoked'

            if worker.get('session_token_jti') and tok_payload.get('jti') != worker.get('session_token_jti'):
                return False, worker, 'stale token'

            self._cleanup_replay_guard()
            if message_id in self.replay_guard:
                self._adjust_worker_trust_locked(worker, -TRUST_AUTH_FAIL_PENALTY, 'replay detected')
                self.save_state()
                return False, worker, 'replay detected'
            self.replay_guard[message_id] = now

        return True, None, 'ok'

    def _enforce_worker_request_or_penalize(self, payload, permission):
        ok, worker, reason = self._verify_worker_request(payload, permission)
        if ok:
            logger.info(
                "AUTH_ACCEPT | worker=%s perm=%s msg=%s",
                payload.get('worker_id') if isinstance(payload, dict) else 'unknown',
                permission,
                payload.get('message_id') if isinstance(payload, dict) else None
            )
            return True, 'ok'

        worker_id = payload.get('worker_id') if isinstance(payload, dict) else None
        with self.worker_lock:
            if worker is None and worker_id:
                worker = self._find_worker_by_id_locked(worker_id)
            if worker is not None:
                # Do not penalize while worker is not yet allowed in join flow.
                if worker.get('join_state', 'pending') != 'allowed':
                    logger.info(
                        "AUTH_REJECT_PREJOIN | worker=%s perm=%s reason=%s",
                        worker.get('worker_id'),
                        permission,
                        reason
                    )
                    return False, reason
                self._adjust_worker_trust_locked(worker, -TRUST_AUTH_FAIL_PENALTY, f'auth failure: {reason}')
                self.save_state()
                logger.warning(
                    "AUTH_REJECT | worker=%s perm=%s reason=%s msg=%s",
                    worker.get('worker_id'),
                    permission,
                    reason,
                    payload.get('message_id') if isinstance(payload, dict) else None
                )
        return False, reason
    
    def get_machine_id(self):
        """Get unique machine identifier"""
        try:
            with open('/etc/machine-id', 'r') as f:
                return f.read().strip()[:16]
        except:
            return socket.gethostname()
    
    def load_state(self):
        """Load previous master state"""
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, 'r') as f:
                    state = json.load(f)
                    self.onboarded_workers = state.get('onboarded_workers', {})
                    self.next_worker_ip = state.get('next_worker_ip', WORKER_IP_START)
                    self.detected_workers = state.get('detected_workers', {})
                    self.fl_round_state = state.get('fl_round_state', self.fl_round_state)
                    self.task_state = state.get('task_state', self.task_state)
                    self.master_benchmark_report = state.get('master_benchmark_report', {})
                    known_count = len(self.onboarded_workers)
                    online_count = 0
                    recently_seen_count = 0
                    now = datetime.now()

                    for worker in self.onboarded_workers.values():
                        if worker.get('status') == 'online':
                            online_count += 1

                        last_seen_str = worker.get('last_seen')
                        if not last_seen_str:
                            continue
                        try:
                            last_seen = datetime.fromisoformat(last_seen_str)
                        except Exception:
                            continue
                        if (now - last_seen).total_seconds() <= HEARTBEAT_TIMEOUT:
                            recently_seen_count += 1

                    logger.info(
                        "Loaded state: %d known worker record(s) (%d online, %d seen within %ds)",
                        known_count,
                        online_count,
                        recently_seen_count,
                        HEARTBEAT_TIMEOUT,
                    )
        except Exception as e:
            logger.error(f"Error loading state: {e}")
    
    def save_state(self):
        """Persist master state"""
        try:
            state = {
                'master_id': self.master_id,
                'onboarded_workers': self.onboarded_workers,
                'detected_workers': self.detected_workers,
                'next_worker_ip': self.next_worker_ip,
                'fl_round_state': self.fl_round_state,
                'task_state': self.task_state,
                'master_benchmark_report': self.master_benchmark_report,
                'timestamp': datetime.now().isoformat()
            }
            with open(STATE_FILE, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving state: {e}")

    def mark_topology_dirty(self, reason):
        self.topology_dirty = True
        logger.info(f"Topology changed ({reason}); benchmark refresh scheduled")

    def _run_quick_cpu_benchmark(self):
        try:
            out = subprocess.getoutput("sysbench cpu --threads=$(nproc) --cpu-max-prime=15000 run")
            for line in out.splitlines():
                low = line.strip().lower()
                if 'events per second' in low:
                    return float(low.split(':')[-1].strip())
            return float(os.cpu_count() or 1) * 1000.0
        except Exception:
            return float(os.cpu_count() or 1) * 1000.0

    def _read_local_cpu_usage_percent(self):
        try:
            with open('/proc/stat', 'r') as f:
                first = f.readline().strip().split()
            if len(first) < 5 or first[0] != 'cpu':
                return 0.0

            values = [int(v) for v in first[1:]]
            idle = values[3] + (values[4] if len(values) > 4 else 0)
            total = sum(values)

            if self.master_cpu_prev_total is None or self.master_cpu_prev_idle is None:
                self.master_cpu_prev_total = total
                self.master_cpu_prev_idle = idle
                return 0.0

            delta_total = total - self.master_cpu_prev_total
            delta_idle = idle - self.master_cpu_prev_idle
            self.master_cpu_prev_total = total
            self.master_cpu_prev_idle = idle

            if delta_total <= 0:
                return 0.0

            usage = (1.0 - (delta_idle / float(delta_total))) * 100.0
            return round(max(0.0, min(100.0, usage)), 2)
        except Exception:
            return 0.0

    def _read_local_memory_stats(self):
        mem_total_kb = 0.0
        mem_available_kb = 0.0
        try:
            with open('/proc/meminfo', 'r') as f:
                for line in f:
                    if line.startswith('MemTotal:'):
                        mem_total_kb = float(line.split()[1])
                    elif line.startswith('MemAvailable:'):
                        mem_available_kb = float(line.split()[1])
            if mem_total_kb <= 0:
                return 0.0, 0.0

            used_pct = ((mem_total_kb - mem_available_kb) / mem_total_kb) * 100.0
            available_gb = mem_available_kb / (1024.0 * 1024.0)
            return round(max(0.0, min(100.0, used_pct)), 2), round(max(0.0, available_gb), 2)
        except Exception:
            return 0.0, 0.0

    def _collect_local_live_metrics(self):
        mem_used_pct, mem_available_gb = self._read_local_memory_stats()
        load_1m = 0.0
        try:
            load_1m = round(float(os.getloadavg()[0]), 2)
        except Exception:
            load_1m = 0.0
        return {
            'cpu_usage_percent': self._read_local_cpu_usage_percent(),
            'memory_usage_percent': mem_used_pct,
            'memory_available_gb': mem_available_gb,
            'load_1m': load_1m,
            'timestamp': datetime.now().isoformat()
        }

    def collect_master_benchmark(self):
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

        self.master_benchmark_report = {
            'worker_id': self.master_id,
            'hostname': socket.gethostname(),
            'os': platform.system() + ' ' + platform.release(),
            'cpu_model': subprocess.getoutput("lscpu | grep 'Model name' | awk -F ':' '{print $2}' | xargs"),
            'cpu_cores': int(os.cpu_count() or 1),
            'memory_gb': memory_gb,
            'cpu_benchmark': f"{self._run_quick_cpu_benchmark():.2f} events/sec",
            'network': {'download_mbps': 0.0, 'upload_mbps': 0.0, 'error': 'master-network-skip'},
            'timestamp': datetime.now().isoformat()
        }
        self.save_state()

    def _send_worker_command(self, worker, payload):
        worker_ip = worker.get('observed_ip') or worker.get('assigned_ip')
        if not worker_ip:
            return False, 'worker has no reachable IP'

        payload = dict(payload)
        payload.setdefault('message_id', f"msg-{uuid.uuid4().hex[:12]}")
        payload.setdefault('sent_at', datetime.now().isoformat())
        payload['checksum'] = sign_payload(payload)

        last_error = None
        # Worker listener accepts commands in a polling loop; stretch retry window
        # to tolerate short listen gaps and transient connection-refused races.
        max_attempts = 10
        for attempt in range(1, max_attempts + 1):
            try:
                sock = socket.create_connection((worker_ip, WORKER_COMMAND_PORT), timeout=4)
                sock.sendall(json.dumps(payload).encode('utf-8'))
                sock.shutdown(socket.SHUT_WR)
                sock.settimeout(4)
                ack_raw = sock.recv(4096)
                sock.close()

                if not ack_raw:
                    last_error = 'no ack from worker'
                else:
                    try:
                        ack = json.loads(ack_raw.decode('utf-8'))
                    except Exception:
                        return False, 'invalid ack format'

                    ack_status = ack.get('ack_status')
                    ack_message_id = ack.get('message_id')
                    if ack_message_id != payload.get('message_id'):
                        return False, 'ack message_id mismatch'

                    if ack_status in ('accepted', 'duplicate'):
                        return True, ack_status
                    return False, ack.get('reason') or 'worker rejected command'
            except Exception as e:
                last_error = str(e)

            if attempt < max_attempts:
                time.sleep(1.0)

        return False, f"{last_error} (target={worker_ip}:{WORKER_COMMAND_PORT})"

    def trigger_cluster_benchmark(self):
        if not BENCHMARK_ON_TOPOLOGY_CHANGE:
            return

        now = time.time()
        if (now - self.last_benchmark_dispatch_at) < BENCHMARK_REDISPATCH_COOLDOWN:
            return

        online_workers = self._get_online_workers()
        self.collect_master_benchmark()

        for worker in online_workers:
            command = {
                'action': 'run_benchmark',
                'benchmark_request_id': f"bench-{uuid.uuid4().hex[:10]}",
                'master_url': f'http://{MASTER_IP}:{MASTER_LISTEN_PORT}/api/worker/report'
            }
            ok, reason = self._send_worker_command(worker, command)
            if not ok:
                logger.warning(f"Benchmark command dispatch failed for {worker.get('worker_id')}: {reason}")

        self.last_benchmark_dispatch_at = now
        self.topology_dirty = False
        logger.info(f"Benchmark refresh dispatched to {len(online_workers)} online worker(s)")

    def refresh_benchmarks_now(self):
        """Manual benchmark refresh from dashboard button.

        Bypasses cooldown and topology-dirty guard for explicit user action.
        """
        online_workers = self._get_online_workers()
        self.collect_master_benchmark()

        dispatched = 0
        failed = []
        for worker in online_workers:
            command = {
                'action': 'run_benchmark',
                'benchmark_request_id': f"bench-manual-{uuid.uuid4().hex[:10]}",
                'master_url': f'http://{MASTER_IP}:{MASTER_LISTEN_PORT}/api/worker/report'
            }
            ok, reason = self._send_worker_command(worker, command)
            if ok:
                dispatched += 1
            else:
                failed.append({'worker_id': worker.get('worker_id'), 'reason': reason})

        self.last_benchmark_dispatch_at = time.time()
        self.topology_dirty = False

        data = {
            'online_workers': len(online_workers),
            'dispatched': dispatched,
            'failed': failed
        }
        return True, data, 'benchmark refresh requested'
    
    def scan_network_arp(self):
        """Scan network for devices"""
        try:
            result = subprocess.run(
                ['arp', '-n'],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            devices = []
            for line in result.stdout.split('\n')[1:]:
                parts = line.split()
                if len(parts) >= 3:
                    ip = parts[0]
                    mac = parts[2].upper()
                    
                    if mac != '(INCOMPLETE)' and ip != MASTER_IP and ip != ROUTER_GATEWAY:
                        devices.append((ip, mac))
            
            return devices
        
        except Exception as e:
            logger.error(f"Error scanning network: {e}")
            return []
    
    def handle_worker_announcement(self, announcement):
        """
        Handle worker announcement (worker announces itself after connecting)
        This is called when worker listener daemon sends presence announcement
        """
        worker_id = announcement.get('worker_id')
        mac = announcement.get('mac_address')
        hostname = announcement.get('hostname')
        observed_ip = announcement.get('master_observed_ip')

        ok, reason = self._validate_required_fields(
            announcement,
            ['worker_id', 'mac_address', 'hostname', 'timestamp', 'checksum']
        )
        if not ok:
            logger.warning(f"Invalid announcement payload: {reason}")
            return False, reason

        if not verify_payload_checksum(announcement):
            logger.warning(f"Rejected announcement with invalid checksum from worker {worker_id}")
            return False, 'invalid checksum'
        
        logger.info(f"Worker {worker_id} announced itself - {hostname} ({mac})")
        self.audit.log('DISCOVERED', worker_id, f"MAC: {mac}, Hostname: {hostname}")
        
        with self.worker_lock:
            # Check if already known
            is_known = any(
                w.get('worker_id') == worker_id 
                for w in self.onboarded_workers.values()
            )
            
            if not is_known:
                if AUTO_ONBOARD_ON_ANNOUNCE:
                    assigned_ip = f"192.168.0.{self.next_worker_ip}"
                    self.next_worker_ip += 1
                    self.onboarded_workers[worker_id] = {
                        'worker_id': worker_id,
                        'mac': mac,
                        'hostname': hostname,
                        'assigned_ip': assigned_ip,
                        'observed_ip': observed_ip,
                        'public_key': None,
                        'status': 'pending',
                        'onboarded_at': datetime.now().isoformat(),
                        'last_seen': datetime.now().isoformat(),
                        'benchmark_report': {},
                        'worker_score': 0.0,
                        'canary_required': True,
                        'canary_passed_at': None,
                        'join_state': 'pending',
                        'trust_score': TRUST_INITIAL_SCORE,
                        'quarantined': False,
                        'quarantine_reason': None,
                        'quarantined_at': None,
                        'quarantine_release_at': None,
                        'token_revoked': False
                    }
                    self.audit.log('ACCEPTED_AUTO', worker_id, f"Assigned IP: {assigned_ip}")
                    self.mark_topology_dirty('worker joined')
                else:
                    # Store as detected
                    self.detected_workers[mac] = {
                        'worker_id': worker_id,
                        'mac': mac,
                        'hostname': hostname,
                        'observed_ip': observed_ip,
                        'announced_at': datetime.now().isoformat(),
                        'last_seen': datetime.now().isoformat(),
                        'status': 'pending_popup'
                    }
            else:
                for _, worker in self.onboarded_workers.items():
                    if worker.get('worker_id') == worker_id:
                        previous_status = worker.get('status')
                        if observed_ip:
                            worker['observed_ip'] = observed_ip
                        worker['last_seen'] = datetime.now().isoformat()
                        # Reconnect should always re-enter pending consent flow.
                        if CONSENT_EVERY_SESSION:
                            worker['join_state'] = 'pending'
                            worker['status'] = 'pending'
                        else:
                            worker['status'] = 'online' if worker.get('join_state') == 'allowed' else 'pending'
                        if CONSENT_EVERY_SESSION:
                            worker['canary_required'] = True
                        # Fresh reconnect starts from clean trust posture until allow.
                        worker['quarantined'] = False
                        worker['quarantine_reason'] = None
                        worker['quarantined_at'] = None
                        worker['quarantine_release_at'] = None
                        worker['trust_score'] = TRUST_INITIAL_SCORE
                        worker['token_revoked'] = False
                        if previous_status != 'online':
                            self.mark_topology_dirty('worker back online')
                        break
            self.save_state()
        
        # Start remote popup trigger only if manual onboarding flow is active
        if not AUTO_ONBOARD_ON_ANNOUNCE:
            Thread(
                target=self.trigger_remote_popup,
                args=(announcement,),
                daemon=True
            ).start()
        return True, 'accepted'

    def handle_worker_heartbeat(self, heartbeat):
        ok, reason = self._validate_required_fields(
            heartbeat,
            ['worker_id', 'hostname', 'timestamp', 'checksum']
        )
        if not ok:
            logger.warning(f"Invalid heartbeat payload: {reason}")
            return False, reason

        if not verify_payload_checksum(heartbeat):
            logger.warning(f"Rejected heartbeat with invalid checksum from worker {heartbeat.get('worker_id')}")
            return False, 'invalid checksum'

        worker_id = heartbeat.get('worker_id')
        heartbeat_time = datetime.now().isoformat()

        with self.worker_lock:
            found = False
            for _, worker in self.onboarded_workers.items():
                if worker.get('worker_id') == worker_id:
                    previous_status = worker.get('status')
                    worker['last_seen'] = heartbeat_time
                    if isinstance(heartbeat.get('live_metrics'), dict):
                        worker['live_metrics'] = heartbeat.get('live_metrics')

                    score_inputs = heartbeat.get('score_inputs') if isinstance(heartbeat.get('score_inputs'), dict) else {}
                    if score_inputs:
                        benchmark = worker.get('benchmark_report', {}) if isinstance(worker.get('benchmark_report'), dict) else {}
                        before = (
                            benchmark.get('cpu_cores'),
                            benchmark.get('memory_gb'),
                            benchmark.get('cpu_benchmark'),
                            (benchmark.get('network') or {}).get('download_mbps') if isinstance(benchmark.get('network'), dict) else None,
                            (benchmark.get('network') or {}).get('upload_mbps') if isinstance(benchmark.get('network'), dict) else None,
                        )

                        benchmark['cpu_cores'] = score_inputs.get('cpu_cores', benchmark.get('cpu_cores'))
                        benchmark['memory_gb'] = score_inputs.get('memory_gb', benchmark.get('memory_gb'))
                        benchmark['cpu_benchmark'] = score_inputs.get('cpu_benchmark', benchmark.get('cpu_benchmark'))
                        incoming_network = score_inputs.get('network') if isinstance(score_inputs.get('network'), dict) else {}
                        prev_network = benchmark.get('network') if isinstance(benchmark.get('network'), dict) else {}
                        benchmark['network'] = {
                            'download_mbps': incoming_network.get('download_mbps', prev_network.get('download_mbps', 0.0)),
                            'upload_mbps': incoming_network.get('upload_mbps', prev_network.get('upload_mbps', 0.0))
                        }
                        worker['benchmark_report'] = benchmark

                        after = (
                            benchmark.get('cpu_cores'),
                            benchmark.get('memory_gb'),
                            benchmark.get('cpu_benchmark'),
                            benchmark['network'].get('download_mbps'),
                            benchmark['network'].get('upload_mbps'),
                        )
                        if before != after:
                            worker['benchmark_updated_at'] = heartbeat_time
                            self._recompute_worker_scores_locked()

                    join_state = worker.get('join_state', 'pending')
                    if join_state == 'allowed':
                        worker['status'] = 'online'
                    elif join_state == 'denied':
                        worker['status'] = 'offline'
                    else:
                        worker['status'] = 'pending'
                    if heartbeat.get('master_observed_ip'):
                        worker['observed_ip'] = heartbeat.get('master_observed_ip')
                    # Only topology-bump when worker transitions into online.
                    if worker.get('status') == 'online' and previous_status != 'online':
                        self.mark_topology_dirty('worker heartbeat online')
                    found = True
                    break

            if not found:
                for _, worker in self.detected_workers.items():
                    if worker.get('worker_id') == worker_id:
                        worker['last_seen'] = heartbeat_time
                        worker['status'] = 'online'
                        if isinstance(heartbeat.get('live_metrics'), dict):
                            worker['live_metrics'] = heartbeat.get('live_metrics')
                        found = True
                        break

            if not found:
                logger.info(f"Heartbeat received from unknown worker {worker_id}; treating as discovered")
                heartbeat_key = heartbeat.get('mac_address') or worker_id
                self.detected_workers[heartbeat_key] = {
                    'worker_id': worker_id,
                    'mac': heartbeat.get('mac_address', 'unknown'),
                    'hostname': heartbeat.get('hostname', 'unknown'),
                    'announced_at': heartbeat_time,
                    'last_seen': heartbeat_time,
                    'status': 'online',
                    'live_metrics': heartbeat.get('live_metrics', {}) if isinstance(heartbeat.get('live_metrics'), dict) else {}
                }

            self.save_state()

        return True, 'heartbeat accepted'

    def reconcile_worker_liveness(self):
        now = datetime.now()
        changed = False

        def _offline_if_stale(worker):
            nonlocal changed
            last_seen_str = worker.get('last_seen')
            if not last_seen_str:
                return
            try:
                last_seen = datetime.fromisoformat(last_seen_str)
            except Exception:
                return

            if (now - last_seen).total_seconds() > HEARTBEAT_TIMEOUT and worker.get('status') != 'disconnected':
                worker['status'] = 'disconnected'
                # Broken trust on disconnect: reconnect must go through join flow again.
                if CONSENT_EVERY_SESSION:
                    worker['join_state'] = 'pending'
                self.mark_topology_dirty('worker disconnected')
                changed = True

        with self.worker_lock:
            for _, worker in self.onboarded_workers.items():
                _offline_if_stale(worker)
            for _, worker in self.detected_workers.items():
                _offline_if_stale(worker)

            if changed:
                self.save_state()

    # -------------------- FL SCAFFOLD (PHASE-1) --------------------
    def start_fl_round(self, round_id, model_version='v0'):
        if not FL_ENABLED:
            return False, 'fl disabled'

        with self.worker_lock:
            online_workers = [
                w.get('worker_id')
                for w in self.onboarded_workers.values()
                if w.get('status') == 'online'
            ]

        if len(online_workers) < FL_MIN_CLIENTS:
            return False, f'insufficient clients ({len(online_workers)}/{FL_MIN_CLIENTS})'

        self.fl_round_state['current_round'] = round_id
        self.fl_round_state['rounds'][round_id] = {
            'model_version': model_version,
            'participants': online_workers,
            'updates': {},
            'status': 'collecting',
            'started_at': datetime.now().isoformat(),
            'timeout_seconds': FL_ROUND_TIMEOUT
        }
        self.save_state()
        logger.info(f"FL round {round_id} started with {len(online_workers)} participants")
        return True, 'round started'

    def collect_fl_update(self, update):
        ok, reason = self._validate_required_fields(
            update,
            ['worker_id', 'round_id', 'update_payload', 'timestamp', 'checksum']
        )
        if not ok:
            return False, reason

        if not verify_payload_checksum(update):
            return False, 'invalid checksum'

        round_id = update.get('round_id')
        worker_id = update.get('worker_id')
        round_data = self.fl_round_state['rounds'].get(round_id)

        if not round_data:
            return False, 'unknown round'

        if worker_id in round_data.get('updates', {}):
            return True, 'duplicate update ignored'

        round_data['updates'][worker_id] = update.get('update_payload')
        round_data['last_update_at'] = datetime.now().isoformat()
        self.save_state()
        return True, 'update accepted'

    def aggregate_fedavg(self, round_id):
        round_data = self.fl_round_state['rounds'].get(round_id)
        if not round_data:
            return False, None, 'unknown round'

        updates = round_data.get('updates', {})
        if not updates:
            return False, None, 'no updates available'

        # Phase-1: scaffold aggregation metadata only.
        # Real tensor averaging will be implemented in Phase-2.
        aggregate_summary = {
            'client_updates': len(updates),
            'participants': round_data.get('participants', []),
            'aggregated_at': datetime.now().isoformat()
        }

        round_data['status'] = 'aggregated'
        round_data['aggregate_summary'] = aggregate_summary
        self.fl_round_state['current_round'] = None
        self.save_state()
        return True, aggregate_summary, 'aggregated'

    # -------------------- PHASE-1 SCHEDULER/TASK LIFECYCLE --------------------
    def _parse_cpu_benchmark(self, benchmark_str):
        if not benchmark_str:
            return 0.0
        text = str(benchmark_str)
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)", text)
        if not match:
            return 0.0
        try:
            return float(match.group(1))
        except Exception:
            return 0.0

    def _safe_float(self, value, default=0.0):
        """Parse numeric-like values without breaking overview rendering."""
        try:
            if value is None:
                return float(default)
            if isinstance(value, (int, float)):
                return float(value)
            text = str(value).strip()
            # Accept strings like "12 cores" / "8.0 GB" by extracting first number.
            match = re.search(r"([0-9]+(?:\.[0-9]+)?)", text)
            if match:
                return float(match.group(1))
            return float(default)
        except Exception:
            return float(default)

    def _compute_worker_raw_strength(self, worker):
        benchmark = worker.get('benchmark_report', {})
        cpu_events = self._parse_cpu_benchmark(benchmark.get('cpu_benchmark'))
        network = benchmark.get('network', {}) if isinstance(benchmark.get('network'), dict) else {}
        download = self._safe_float(network.get('download_mbps', 0.0), 0.0)
        upload = self._safe_float(network.get('upload_mbps', 0.0), 0.0)
        cores = self._safe_float(benchmark.get('cpu_cores', 0), 0.0)
        memory = self._safe_float(benchmark.get('memory_gb', 0.0), 0.0)

        # CPU benchmark is primary. If absent, fallback to a cores-derived proxy.
        cpu_capacity = cpu_events if cpu_events > 0 else max(1.0, cores) * 1000.0
        mem_capacity = max(0.0, memory) * SCORE_MEM_SCALE
        net_capacity = max(0.0, (download * 0.7) + (upload * 0.3)) * SCORE_NET_SCALE

        raw_strength = (
            SCORE_CPU_WEIGHT * cpu_capacity +
            SCORE_MEM_WEIGHT * mem_capacity +
            SCORE_NET_WEIGHT * net_capacity
        )
        return {
            'raw_strength': max(0.0, raw_strength),
            'cpu_capacity': cpu_capacity,
            'memory_capacity': mem_capacity,
            'network_capacity': net_capacity
        }

    def compute_cluster_share_scores(self, workers):
        """Return per-worker dynamic share scores whose total is always 100."""
        if not workers:
            return {}

        rows = []
        for worker in workers:
            worker_id = worker.get('worker_id')
            if not worker_id:
                continue
            components = self._compute_worker_raw_strength(worker)
            raw_strength = components['raw_strength']
            adjusted_strength = pow(raw_strength, SCORE_GAMMA) if raw_strength > 0 else 0.0
            rows.append({
                'worker_id': worker_id,
                'raw_strength': raw_strength,
                'adjusted_strength': adjusted_strength,
                'cpu_capacity': components['cpu_capacity'],
                'memory_capacity': components['memory_capacity'],
                'network_capacity': components['network_capacity']
            })

        if not rows:
            return {}

        total_strength = sum(row['adjusted_strength'] for row in rows)
        if total_strength <= 0:
            equal_share = 100.0 / len(rows)
            for row in rows:
                row['worker_score'] = equal_share
        else:
            for row in rows:
                row['worker_score'] = (row['adjusted_strength'] * 100.0) / total_strength

        # Keep visible sum stable at 100.00 after rounding.
        rounded_scores = [round(row['worker_score'], 2) for row in rows]
        rounding_delta = round(100.0 - sum(rounded_scores), 2)
        if rounded_scores:
            rounded_scores[-1] = round(rounded_scores[-1] + rounding_delta, 2)

        score_map = {}
        for idx, row in enumerate(rows):
            score_map[row['worker_id']] = {
                'worker_score': rounded_scores[idx],
                'worker_strength': round(row['adjusted_strength'], 2),
                'worker_raw_strength': round(row['raw_strength'], 2),
                'score_cpu_capacity': round(row['cpu_capacity'], 2),
                'score_memory_capacity': round(row['memory_capacity'], 2),
                'score_network_capacity': round(row['network_capacity'], 2)
            }
        return score_map

    def _recompute_worker_scores_locked(self):
        """Recompute and persist dynamic scores for currently active/allowed workers."""
        online = []
        for worker_id, worker in self.onboarded_workers.items():
            if worker.get('status') == 'online' and worker.get('join_state', 'pending') == 'allowed':
                if worker.get('quarantined'):
                    continue
                online.append({
                    'worker_id': worker_id,
                    'benchmark_report': worker.get('benchmark_report', {})
                })

        score_map = self.compute_cluster_share_scores(online)
        for worker_id, worker in self.onboarded_workers.items():
            score_data = score_map.get(worker_id, {})
            worker['worker_score'] = score_data.get('worker_score', 0.0)
            worker['worker_strength'] = score_data.get('worker_strength', 0.0)

    def _get_online_workers(self):
        workers = []
        with self.worker_lock:
            for worker_id, worker in self.onboarded_workers.items():
                if worker.get('status') == 'online' and worker.get('join_state', 'pending') == 'allowed':
                    if worker.get('quarantined'):
                        continue
                    worker_copy = dict(worker)
                    worker_copy['worker_id'] = worker_id
                    workers.append(worker_copy)

        score_map = self.compute_cluster_share_scores(workers)
        for worker in workers:
            score_data = score_map.get(worker.get('worker_id'), {})
            worker['worker_score'] = score_data.get('worker_score', 0.0)
            worker['worker_strength'] = score_data.get('worker_strength', 0.0)
            worker['worker_raw_strength'] = score_data.get('worker_raw_strength', 0.0)

        workers.sort(key=lambda w: w.get('worker_score', 0.0), reverse=True)
        return workers

    def _get_active_loads(self):
        loads = {}
        with self.worker_lock:
            for task in self.task_state.get('active_tasks', {}).values():
                wid = task.get('assigned_worker')
                if not wid:
                    continue
                loads[wid] = loads.get(wid, 0) + 1
        return loads

    def split_job_into_chunks(self, raw_text):
        lines = [ln for ln in str(raw_text).splitlines() if ln.strip()]
        if not lines:
            return []

        target_size = CHUNK_MIN_LINES
        if len(lines) > CHUNK_MAX_LINES:
            # scale chunk size for larger input, but clamp to guardrails
            target_size = min(max(len(lines) // 8, CHUNK_MIN_LINES), CHUNK_MAX_LINES)

        chunks = []
        for i in range(0, len(lines), target_size):
            chunk_lines = lines[i:i + target_size]
            if chunk_lines:
                chunks.append('\n'.join(chunk_lines))
        return chunks

    def submit_job(self, payload):
        ok, reason = self._validate_required_fields(payload, ['job_data'])
        if not ok:
            return False, None, reason

        chunks = self.split_job_into_chunks(payload.get('job_data'))
        if not chunks:
            return False, None, 'job_data produced no valid chunks'

        job_id = f"job-{uuid.uuid4().hex[:12]}"
        now = datetime.now().isoformat()

        job_entry = {
            'job_id': job_id,
            'submitted_at': now,
            'status': 'queued',
            'total_tasks': len(chunks),
            'completed_tasks': 0,
            'failed_tasks': 0,
            'results': {},
            'keywords': payload.get('keywords', ['ERROR', 'CRITICAL', 'WARN'])
        }

        with self.worker_lock:
            self.task_state['jobs'][job_id] = job_entry
            for idx, chunk in enumerate(chunks):
                task_id = f"{job_id}-t{idx + 1}"
                task = {
                    'task_id': task_id,
                    'job_id': job_id,
                    'status': 'pending',
                    'attempts': 0,
                    'max_attempts': 3,
                    'chunk_data': chunk,
                    'keywords': job_entry['keywords'],
                    'created_at': now
                }
                self.task_state['pending_tasks'].append(task)

            self.save_state()

        logger.info(f"Queued job {job_id} with {len(chunks)} tasks")
        return True, {'job_id': job_id, 'tasks': len(chunks)}, 'queued'

    def _dispatch_task_to_worker(self, task, worker):
        payload_hash_input = {
            'task_id': task['task_id'],
            'job_id': task['job_id'],
            'chunk_data': task['chunk_data'],
            'keywords': task['keywords']
        }
        payload = {
            'action': 'execute_task',
            'task_id': task['task_id'],
            'job_id': task['job_id'],
            'chunk_data': task['chunk_data'],
            'keywords': task['keywords'],
            'task_payload_hash': hashlib.sha256(_canonical_json(payload_hash_input).encode('utf-8')).hexdigest(),
            'master_url': f'http://{MASTER_IP}:{MASTER_LISTEN_PORT}/api/worker/task-result'
        }
        ok, reason = self._send_worker_command(worker, payload)
        return ok, ('dispatched' if ok else reason)

    def assign_pending_tasks(self):
        workers = self._get_online_workers()
        if not workers:
            return

        loads = self._get_active_loads()

        # Pass 1: canary assignment for newly joined/rejoined workers
        for worker in workers:
            worker_id = worker.get('worker_id')
            if loads.get(worker_id, 0) > 0:
                continue
            if not worker.get('canary_required', False):
                continue

            with self.worker_lock:
                pending = self.task_state['pending_tasks']
                if not pending:
                    break
                # choose smallest task as canary
                idx = min(range(len(pending)), key=lambda i: len(str(pending[i].get('chunk_data', ''))))
                task = pending.pop(idx)

            task['is_canary'] = True
            ok, reason = self._dispatch_task_to_worker(task, worker)
            with self.worker_lock:
                if ok:
                    task['status'] = 'active'
                    task['assigned_worker'] = worker_id
                    task['assigned_at'] = datetime.now().isoformat()
                    task['attempts'] = int(task.get('attempts', 0)) + 1
                    self.task_state['active_tasks'][task['task_id']] = task
                    loads[worker_id] = loads.get(worker_id, 0) + 1
                    logger.info(f"Assigned canary task {task['task_id']} -> {worker_id}")
                else:
                    task['status'] = 'pending'
                    task['last_error'] = reason
                    self.task_state['pending_tasks'].append(task)
                    logger.warning(f"Canary dispatch failed for {task['task_id']}: {reason}")
                self.save_state()

        with self.worker_lock:
            pending = self.task_state['pending_tasks']
            if not pending:
                return

            assignments = []
            worker_cycle = list(workers)
            while pending and worker_cycle:
                task = pending.pop(0)
                selected = None

                for _ in range(len(worker_cycle)):
                    candidate = worker_cycle[0]
                    worker_cycle = worker_cycle[1:] + [candidate]
                    wid = candidate.get('worker_id')
                    if loads.get(wid, 0) >= MAX_ACTIVE_TASKS_PER_WORKER:
                        continue
                    if candidate.get('canary_required', False):
                        continue
                    selected = candidate
                    break

                if not selected:
                    pending.insert(0, task)
                    break

                assignments.append((task, selected))
                loads[selected.get('worker_id')] = loads.get(selected.get('worker_id'), 0) + 1

        for task, worker in assignments:
            ok, reason = self._dispatch_task_to_worker(task, worker)
            with self.worker_lock:
                if ok:
                    task['status'] = 'active'
                    task['assigned_worker'] = worker['worker_id']
                    task['assigned_at'] = datetime.now().isoformat()
                    task['attempts'] = int(task.get('attempts', 0)) + 1
                    self.task_state['active_tasks'][task['task_id']] = task
                    logger.info(f"Assigned task {task['task_id']} -> {worker['worker_id']}")
                else:
                    task['status'] = 'pending'
                    task['last_error'] = reason
                    self.task_state['pending_tasks'].append(task)
                    logger.warning(f"Dispatch failed for {task['task_id']}: {reason}")

                self.save_state()

    def reconcile_task_timeouts(self):
        now = datetime.now()
        requeue = []
        permanently_failed = []

        with self.worker_lock:
            for task_id, task in list(self.task_state['active_tasks'].items()):
                assigned_at = task.get('assigned_at')
                if not assigned_at:
                    continue
                try:
                    assigned_dt = datetime.fromisoformat(assigned_at)
                except Exception:
                    continue

                if (now - assigned_dt).total_seconds() > TASK_TIMEOUT_SECONDS:
                    del self.task_state['active_tasks'][task_id]
                    if int(task.get('attempts', 0)) < int(task.get('max_attempts', 3)):
                        task['status'] = 'pending'
                        task['last_error'] = 'timeout-requeue'
                        if task.get('is_canary'):
                            wid = task.get('assigned_worker')
                            if wid and wid in self.onboarded_workers:
                                self.onboarded_workers[wid]['canary_required'] = True
                        requeue.append(task)
                    else:
                        task['status'] = 'failed'
                        permanently_failed.append(task)

            for task in requeue:
                self.task_state['pending_tasks'].append(task)

            for task in permanently_failed:
                self.task_state['completed_tasks'][task['task_id']] = task
                job = self.task_state['jobs'].get(task['job_id'])
                if job:
                    job['failed_tasks'] = int(job.get('failed_tasks', 0)) + 1

            if requeue or permanently_failed:
                self.save_state()

    def handle_task_result(self, payload):
        ok, reason = self._validate_required_fields(
            payload,
            ['worker_id', 'task_id', 'job_id', 'result', 'timestamp', 'checksum']
        )
        if not ok:
            return False, reason

        if not verify_payload_checksum(payload):
            return False, 'invalid checksum'

        result_obj = payload.get('result')
        claimed_hash = payload.get('result_hash')
        claimed_sig = payload.get('result_signature')
        if claimed_hash and claimed_sig:
            computed_hash = hashlib.sha256(_canonical_json(result_obj).encode('utf-8')).hexdigest()
            if computed_hash != claimed_hash:
                return False, 'result hash mismatch'
            expected_sig = result_signature(payload.get('worker_id'), payload.get('task_id'), claimed_hash)
            if expected_sig != claimed_sig:
                return False, 'result signature invalid'

        task_id = payload.get('task_id')
        job_id = payload.get('job_id')

        with self.worker_lock:
            task = self.task_state['active_tasks'].pop(task_id, None)
            if not task:
                if task_id in self.task_state.get('completed_tasks', {}):
                    return True, 'duplicate result ignored'
                return False, 'unknown task'

            task['status'] = 'completed'
            task['completed_at'] = datetime.now().isoformat()
            task['result'] = payload.get('result')
            self.task_state['completed_tasks'][task_id] = task

            assigned_worker = task.get('assigned_worker')
            if task.get('is_canary') and assigned_worker in self.onboarded_workers:
                self.onboarded_workers[assigned_worker]['canary_required'] = False
                self.onboarded_workers[assigned_worker]['canary_passed_at'] = datetime.now().isoformat()

            job = self.task_state['jobs'].get(job_id)
            if job:
                job['completed_tasks'] = int(job.get('completed_tasks', 0)) + 1
                job['results'][task_id] = payload.get('result')

                if (job['completed_tasks'] + job.get('failed_tasks', 0)) >= job.get('total_tasks', 0):
                    job['status'] = 'completed'
                    job['finished_at'] = datetime.now().isoformat()
                else:
                    job['status'] = 'running'

            self.save_state()

        return True, 'result accepted'

    def get_workers_status(self):
        online_ranked_workers = self._get_online_workers()

        score_population = []
        score_population.append({
            'worker_id': self.master_id,
            'benchmark_report': self.master_benchmark_report or {}
        })
        for worker in online_ranked_workers:
            score_population.append({
                'worker_id': worker.get('worker_id'),
                'benchmark_report': worker.get('benchmark_report', {})
            })

        all_connected_score_map = self.compute_cluster_share_scores(score_population)

        with self.worker_lock:
            active_loads = {}
            for task in self.task_state.get('active_tasks', {}).values():
                wid = task.get('assigned_worker')
                if wid:
                    active_loads[wid] = active_loads.get(wid, 0) + 1

            workers = []
            master_score = all_connected_score_map.get(self.master_id, {}).get('worker_score', 0.0)

            workers.append({
                'worker_id': self.master_id,
                'hostname': self.master_hostname,
                'status': 'online',
                'observed_ip': MASTER_IP,
                'assigned_ip': MASTER_IP,
                'worker_score': master_score,
                'worker_strength': all_connected_score_map.get(self.master_id, {}).get('worker_strength', 0.0),
                'score_cpu_capacity': all_connected_score_map.get(self.master_id, {}).get('score_cpu_capacity', 0.0),
                'score_memory_capacity': all_connected_score_map.get(self.master_id, {}).get('score_memory_capacity', 0.0),
                'score_network_capacity': all_connected_score_map.get(self.master_id, {}).get('score_network_capacity', 0.0),
                'canary_required': False,
                'last_seen': datetime.now().isoformat(),
                'active_tasks': 0,
                'load_percent': 0,
                'activity_state': 'master',
                'join_state': 'allowed',
                'is_master': True,
                'benchmark_updated_at': self.master_benchmark_report.get('timestamp'),
                'trust_score': 100,
                'quarantined': False,
                'quarantine_reason': None,
                'benchmark_report': self.master_benchmark_report or {},
                'score_inputs': {
                    'cpu_cores': (self.master_benchmark_report or {}).get('cpu_cores'),
                    'memory_gb': (self.master_benchmark_report or {}).get('memory_gb'),
                    'cpu_benchmark': (self.master_benchmark_report or {}).get('cpu_benchmark'),
                    'network': ((self.master_benchmark_report or {}).get('network') or {})
                },
                'live_metrics': self._collect_local_live_metrics()
            })

            for worker_id, worker in self.onboarded_workers.items():
                if worker_id == self.master_id:
                    continue

                # Requested behavior: hide unplugged/disconnected workers from dashboard
                # until they reconnect and announce/heartbeat again.
                if worker.get('status') == 'disconnected':
                    continue

                active_tasks = int(active_loads.get(worker_id, 0))
                status = worker.get('status')
                join_state = worker.get('join_state', 'pending')
                if join_state == 'pending' or status == 'pending':
                    activity_state = 'pending'
                elif status != 'online':
                    activity_state = 'offline'
                elif active_tasks > 0:
                    activity_state = 'busy'
                else:
                    activity_state = 'available'

                if activity_state in ('offline', 'pending'):
                    load_percent = 0
                else:
                    load_percent = min(100, int((active_tasks / max(1, MAX_ACTIVE_TASKS_PER_WORKER)) * 100))

                dynamic_score = all_connected_score_map.get(worker_id, {})

                workers.append({
                    'worker_id': worker_id,
                    'hostname': worker.get('hostname'),
                    'status': worker.get('status'),
                    'observed_ip': worker.get('observed_ip'),
                    'assigned_ip': worker.get('assigned_ip'),
                    'worker_score': dynamic_score.get('worker_score', 0.0),
                    'worker_strength': dynamic_score.get('worker_strength', 0.0),
                    'score_cpu_capacity': dynamic_score.get('score_cpu_capacity', 0.0),
                    'score_memory_capacity': dynamic_score.get('score_memory_capacity', 0.0),
                    'score_network_capacity': dynamic_score.get('score_network_capacity', 0.0),
                    'canary_required': worker.get('canary_required', False),
                    'last_seen': worker.get('last_seen'),
                    'active_tasks': active_tasks,
                    'load_percent': load_percent,
                    'activity_state': activity_state,
                    'join_state': worker.get('join_state', 'pending'),
                    'is_master': False,
                    'benchmark_updated_at': worker.get('benchmark_updated_at'),
                    'trust_score': worker.get('trust_score', TRUST_INITIAL_SCORE),
                    'quarantined': worker.get('quarantined', False),
                    'quarantine_reason': worker.get('quarantine_reason'),
                    'quarantined_at': worker.get('quarantined_at'),
                    'quarantine_release_at': worker.get('quarantine_release_at'),
                    'benchmark_report': worker.get('benchmark_report', {}),
                    'score_inputs': {
                        'cpu_cores': (worker.get('benchmark_report') or {}).get('cpu_cores') if isinstance(worker.get('benchmark_report'), dict) else None,
                        'memory_gb': (worker.get('benchmark_report') or {}).get('memory_gb') if isinstance(worker.get('benchmark_report'), dict) else None,
                        'cpu_benchmark': (worker.get('benchmark_report') or {}).get('cpu_benchmark') if isinstance(worker.get('benchmark_report'), dict) else None,
                        'network': ((worker.get('benchmark_report') or {}).get('network') or {}) if isinstance(worker.get('benchmark_report'), dict) else {}
                    },
                    'live_metrics': worker.get('live_metrics', {})
                })

            data = {
                'onboarded_count': len(self.onboarded_workers),
                'detected_count': len(self.detected_workers),
                'workers': workers
            }
        return True, data, 'ok'

    def resolve_worker_id_by_ip(self, ip):
        with self.worker_lock:
            for worker_id, worker in self.onboarded_workers.items():
                if worker.get('observed_ip') == ip:
                    return worker_id
        return None

    def get_worker_join_state(self, worker_id):
        if not worker_id:
            return 'pending'
        with self.worker_lock:
            worker = self.onboarded_workers.get(worker_id)
            if not worker:
                return 'pending'
            return worker.get('join_state', 'pending')

    def set_worker_join_state(self, worker_id, join_state):
        if join_state not in ('allowed', 'denied', 'pending'):
            return False, 'invalid join_state'
        if not worker_id:
            return False, 'worker_id not found for requester IP'
        should_refresh_benchmark = False
        with self.worker_lock:
            worker = self.onboarded_workers.get(worker_id)
            if not worker:
                return False, 'worker not onboarded'
            current = worker.get('join_state', 'pending')
            # Required behavior: if denied initially, allow only after reconnect/session reset.
            if current == 'denied' and join_state == 'allowed':
                return False, 'reconnect required after deny to re-open join flow'
            worker['join_state'] = join_state
            if join_state == 'allowed':
                worker['status'] = 'online'
                should_refresh_benchmark = True
            elif join_state == 'denied':
                worker['status'] = 'offline'
            else:
                worker['status'] = 'pending'
            worker['join_state_updated_at'] = datetime.now().isoformat()
            self.save_state()

        logger.info(
            "Join state updated | worker_id=%s hostname=%s %s->%s status=%s",
            worker_id,
            worker.get('hostname'),
            current,
            join_state,
            worker.get('status')
        )

        if should_refresh_benchmark:
            self.mark_topology_dirty('worker allowed')
        return True, 'updated'

    def safety_disconnect_worker(self, worker_id):
        """Force-end a worker session from dashboard safety switch.

        Behavior:
        - Sends terminate command to worker listener to stop the process.
        - Marks worker denied/offline immediately for policy enforcement.
        - If terminate command is ACKed, marks worker disconnected.
        """
        if not worker_id:
            return False, 'worker_id is required'

        worker_snapshot = None
        with self.worker_lock:
            worker = self.onboarded_workers.get(worker_id)
            if not worker:
                return False, 'worker not onboarded'
            worker_snapshot = dict(worker)

        cmd = {
            'action': 'terminate_session',
            'reason': 'safety_disconnect'
        }
        ok_cmd, cmd_reason = self._send_worker_command(worker_snapshot, cmd)

        with self.worker_lock:
            worker = self.onboarded_workers.get(worker_id)
            if not worker:
                return False, 'worker not onboarded'

            worker['join_state'] = 'denied'
            worker['status'] = 'disconnected' if ok_cmd else 'offline'
            worker['join_state_updated_at'] = datetime.now().isoformat()
            worker['token_revoked'] = True
            self.save_state()

        self.mark_topology_dirty('worker safety disconnected')
        if ok_cmd:
            return True, 'worker session terminated'
        return False, f'safety policy applied, but terminate command failed: {cmd_reason}'

    def unquarantine_worker(self, worker_id):
        return self.unquarantine_worker_with_policy(worker_id, force=False, note=None)

    def unquarantine_worker_with_policy(self, worker_id, force=False, note=None):
        if not worker_id:
            return False, 'worker_id is required'

        with self.worker_lock:
            worker = self.onboarded_workers.get(worker_id)
            if not worker:
                return False, 'worker not onboarded'

            release_at_str = worker.get('quarantine_release_at')
            if worker.get('quarantined') and release_at_str and not force:
                try:
                    release_epoch = int(datetime.fromisoformat(release_at_str).timestamp())
                    now_epoch = self._utc_now_epoch()
                    if now_epoch < release_epoch:
                        wait_sec = max(0, release_epoch - now_epoch)
                        return False, f'cooldown active, try again in {wait_sec}s or use force=true'
                except Exception:
                    pass

            worker['quarantined'] = False
            worker['quarantine_reason'] = None
            worker['quarantined_at'] = None
            worker['quarantine_release_at'] = None
            worker['trust_score'] = TRUST_INITIAL_SCORE
            worker['token_revoked'] = False
            worker['trust_updated_at'] = datetime.now().isoformat()
            self.save_state()

        detail = 'manual release by operator'
        if force:
            detail += ' (forced)'
        if note:
            detail += f' note={note}'
        self.audit.log('UNQUARANTINE', worker_id, detail)
        return True, 'worker unquarantined'

    def get_cluster_overview(self):
        ok, workers_data, reason = self.get_workers_status()
        if not ok:
            return False, None, reason

        with self.worker_lock:
            pending_count = len(self.task_state.get('pending_tasks', []))
            active_count = len(self.task_state.get('active_tasks', {}))
            completed_count = len(self.task_state.get('completed_tasks', {}))
            job_count = len(self.task_state.get('jobs', {}))

        summary = {
            'master_status': 'online' if self.running else 'offline',
            'jobs_total': job_count,
            'tasks_pending': pending_count,
            'tasks_active': active_count,
            'tasks_completed': completed_count,
            'onboarded_workers': workers_data.get('onboarded_count', 0),
            'detected_workers': workers_data.get('detected_count', 0)
        }
        master = {
            'master_id': self.master_id,
            'hostname': self.master_hostname,
            'ip': MASTER_IP,
            'port': MASTER_LISTEN_PORT,
            'status': 'online' if self.running else 'offline',
            'started_at': self.started_at
        }

        return True, {'summary': summary, 'master': master, 'workers': workers_data.get('workers', [])}, 'ok'

    def get_job_status(self, job_id):
        if not job_id:
            return False, None, 'job_id is required'

        with self.worker_lock:
            job = self.task_state['jobs'].get(job_id)
            if not job:
                return False, None, 'job not found'

            data = {
                'job_id': job_id,
                'status': job.get('status'),
                'total_tasks': job.get('total_tasks'),
                'completed_tasks': job.get('completed_tasks'),
                'failed_tasks': job.get('failed_tasks'),
                'results_count': len(job.get('results', {}))
            }
            return True, data, 'ok'

    def handle_worker_report(self, report):
        ok, reason = self._validate_required_fields(
            report,
            ['worker_id', 'hostname', 'timestamp', 'checksum']
        )
        if not ok:
            return False, reason

        if not verify_payload_checksum(report):
            return False, 'invalid checksum'

        worker_id = report.get('worker_id')
        hostname = report.get('hostname')
        observed_ip = report.get('master_observed_ip')

        with self.worker_lock:
            target = None

            if worker_id and worker_id in self.onboarded_workers:
                target = self.onboarded_workers[worker_id]
            elif worker_id:
                for _, worker in self.onboarded_workers.items():
                    if worker.get('worker_id') == worker_id:
                        target = worker
                        break

            if not target and hostname:
                for _, worker in self.onboarded_workers.items():
                    if worker.get('hostname') == hostname:
                        target = worker
                        break

            if not target:
                return False, 'worker not onboarded for report'

            target['benchmark_report'] = {
                'hostname': report.get('hostname'),
                'os': report.get('os'),
                'cpu_model': report.get('cpu_model'),
                'cpu_cores': report.get('cpu_cores'),
                'memory_gb': report.get('memory_gb'),
                'cpu_benchmark': report.get('cpu_benchmark'),
                'network': report.get('network', {})
            }
            target['observed_ip'] = observed_ip or target.get('observed_ip')
            target['benchmark_updated_at'] = datetime.now().isoformat()
            target['last_seen'] = datetime.now().isoformat()
            target['status'] = 'online'

            self._recompute_worker_scores_locked()

            self.save_state()

        return True, 'benchmark report ingested'
    
    def trigger_remote_popup(self, worker_info):
        """
        Trigger the popup on the remote worker
        Master sends bootstrap script and triggers it on worker
        """
        worker_id = worker_info.get('worker_id')
        hostname = worker_info.get('hostname')
        mac = worker_info.get('mac_address')
        
        logger.info(f"Triggering remote popup for {worker_id}...")
        self.audit.log('POPUP_TRIGGER', worker_id, "Sending bootstrap to worker")
        
        try:
            # For Lab 1 rework: we'll simulate the popup locally and send response
            # In actual deployment, master would push bootstrap via SSH and trigger it
            
            # Simulate popup on master (or send via SSH to worker in future labs)
            # For now, we'll create a test popup scenario
            
            logger.info(f"Popup triggered for {worker_id}")
            
            # In Lab 2, we'll implement actual remote popup triggering
            # For Lab 1, we're demonstrating the detection and orchestration flow
        
        except Exception as e:
            logger.error(f"Error triggering popup: {e}")
            self.audit.log('ERROR', worker_id, f"Popup trigger failed: {e}")
    
    def handle_worker_response(self, response_data):
        """
        Handle worker response to popup (accepted/rejected)
        """
        worker_id = response_data.get('worker_id')
        response = response_data.get('response')
        
        logger.info(f"Worker {worker_id} response: {response}")
        
        if response == 'accepted':
            self.handle_worker_acceptance(worker_id, response_data)
        elif response == 'rejected':
            self.handle_worker_rejection(worker_id)
    
    def handle_worker_acceptance(self, worker_id, response_data):
        """Handle worker acceptance"""
        logger.info(f"Worker {worker_id} accepted")
        
        try:
            # Find worker in detected
            worker_info = None
            mac = None
            for m, info in self.detected_workers.items():
                if info['worker_id'] == worker_id:
                    worker_info = info
                    mac = m
                    break
            
            if worker_info:
                with self.worker_lock:
                    # Assign IP
                    assigned_ip = f"192.168.0.{self.next_worker_ip}"
                    self.next_worker_ip += 1
                    
                    # Store as onboarded
                    self.onboarded_workers[worker_id] = {
                        'worker_id': worker_id,
                        'mac': mac,
                        'hostname': worker_info['hostname'],
                        'assigned_ip': assigned_ip,
                        'observed_ip': worker_info.get('observed_ip'),
                        'public_key': response_data.get('public_key'),
                        'status': 'online',
                        'onboarded_at': datetime.now().isoformat(),
                        'last_seen': datetime.now().isoformat(),
                        'benchmark_report': {},
                        'worker_score': 0.0,
                        'canary_required': True,
                        'canary_passed_at': None
                    }
                    
                    # Remove from detected
                    if mac in self.detected_workers:
                        del self.detected_workers[mac]
                    
                    self.save_state()
                
                self.audit.log('ACCEPTED', worker_id, f"Assigned IP: {assigned_ip}")
                logger.info(f"Worker {worker_id} onboarded at {assigned_ip}")
        
        except Exception as e:
            logger.error(f"Error handling acceptance: {e}")
    
    def handle_worker_rejection(self, worker_id):
        """Handle worker rejection"""
        logger.info(f"Worker {worker_id} rejected")
        
        try:
            # Remove from detected
            for mac, info in list(self.detected_workers.items()):
                if info['worker_id'] == worker_id:
                    del self.detected_workers[mac]
                    break
            
            self.audit.log('REJECTED', worker_id, "User declined to join")
        
        except Exception as e:
            logger.error(f"Error handling rejection: {e}")
    
    def start_http_server(self):
        """Start HTTP server for worker announcements"""
        logger.info(f"Starting HTTP server on port {MASTER_LISTEN_PORT}")
        
        WorkerAnnounceHandler.master_daemon = self
        
        server = HTTPServer(('0.0.0.0', MASTER_LISTEN_PORT), WorkerAnnounceHandler)
        
        server_thread = Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        
        return server
    
    def run(self):
        """Main daemon loop"""
        logger.info("=" * 60)
        logger.info("GridMind Master Daemon Starting (Lab 1 Rework)")
        logger.info(f"Version: {PROJECT_VERSION}")
        logger.info(f"Master ID: {self.master_id}")
        logger.info(f"Master IP: {MASTER_IP}")
        logger.info(f"Listening on port: {MASTER_LISTEN_PORT}")
        logger.info("=" * 60)
        
        # Start HTTP server
        self.start_http_server()
        
        # Signal handlers
        signal.signal(signal.SIGTERM, self.shutdown)
        signal.signal(signal.SIGINT, self.shutdown)
        
        last_scan = 0
        
        while self.running:
            try:
                current_time = time.time()
                
                # Periodic network scan (for detection without announcements)
                if current_time - last_scan >= SCAN_INTERVAL:
                    last_scan = current_time
                    
                    devices = self.scan_network_arp()
                    logger.debug(f"Network scan found {len(devices)} devices")

                    # Keep online/offline status consistent even during quiet periods
                    self.reconcile_worker_liveness()

                # Phase-1 task lifecycle loop
                self.reconcile_task_timeouts()
                self.assign_pending_tasks()

                if self.topology_dirty:
                    self.trigger_cluster_benchmark()
                
                time.sleep(1)
            
            except KeyboardInterrupt:
                logger.info("Daemon interrupted")
                break
            except Exception as e:
                logger.error(f"Daemon error: {e}")
                time.sleep(5)
    
    def shutdown(self, signum=None, frame=None):
        """Graceful shutdown"""
        logger.info("Master Daemon shutting down...")
        self.running = False
        self.save_state()
        sys.exit(0)

if __name__ == '__main__':
    daemon = MasterDaemon()
    daemon.run()
