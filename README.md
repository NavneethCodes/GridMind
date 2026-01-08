# 🚀 GridMind: Phase 2 "Fresh Start" Roadmap

**Constraint:** 0 Internet (Offline LAN).
**Core Architecture:**
1.  **Gatekeeper:** Python Flask (`app.py`) manages Network Admission & DHCP.
2.  **Brain:** Spring Boot manages Job Distribution, Zero Trust Verification & State.
3.  **Face:** Angular Dashboard for visualization.
4.  **Muscle:** Python Agents on workers.

---

## 👨‍💻 Navneeth (Lead & Backend)
**Focus:** Infrastructure Bridge, Zero Trust Engine, & Core API.
**Directory:** `gridmind-master/`

### ✅ Task 1: The "State Bridge" (Node Registry)
* **Goal:** Auto-detect nodes authorized by the Python Portal without running nmap.
* **File:** `src/main/java/com/gridmind/service/NodeRegistryService.java`
* **Logic:**
    * Implement a **File Watcher** that monitors `workers.json` (created by `app.py`).
    * When the file changes, parse the JSON and update the in-memory `List<Node>`.
    * **Status Mapping:** New nodes start as `IDLE` (Green).

### ✅ Task 2: The Zero Trust Engine
* **Goal:** Verify a node is genuine before sending sensitive data.
* **File:** `src/main/java/com/gridmind/service/ZeroTrustService.java`
* **Logic:**
    * **Algorithm:** Replicate the Python token logic: `SHA256("edge123" + timestamp_minutes)`.
    * **Handshake:** Open a socket to the Worker (Port 5555), send `{"cmd": "VERIFY_TRUST"}`, and compare the returned token with the local calculation.
    * **Return:** `true` if tokens match, `false` if they differ.

### ✅ Task 3: The Job Scheduler
* **Goal:** Split logs and distribute them securely.
* **File:** `src/main/java/com/gridmind/service/JobDispatcher.java`
* **Logic:**
    1.  **Split:** Break the master log file into chunks (Java IO).
    2.  **Verify:** Call `ZeroTrustService.verifyNodeTrust(ip)`.
    3.  **Dispatch:** If trusted, use `JSch` (SSH) to SCP the chunk + agent script to the worker.
    4.  **Execute:** Trigger the analysis command remotely.

### ✅ Task 4: API Layer (For Adish)
* **Goal:** Provide data to the Frontend.
* **File:** `src/main/java/com/gridmind/controller/GridController.java`
* **Endpoints:**
    * `GET /api/nodes` -> Returns list of workers + `trusted` boolean status.
    * `POST /api/jobs/submit` -> Accepts file upload.
    * `GET /api/results` -> Returns aggregated anomaly counts.

---

## 👨‍🎨 Adish (Frontend Specialist)
**Focus:** Visualizing the Grid & Trust Status.
**Directory:** `gridmind-ui/`

### ✅ Task 1: Grid Visualization (The "Shield" Update)
* **Goal:** Show 4 nodes with their real-time trust status.
* **Component:** `NodeGridComponent`
* **Logic:**
    * Poll `GET /api/nodes` every 2 seconds.
    * **Visuals:**
        * **Status Color:** Green (Idle) / Yellow (Busy) / Red (Offline).
        * **Trust Icon:** 🛡️ Green Shield (Trusted) vs. 💔 Broken Shield (Untrusted).

### ✅ Task 2: Job Launchpad
* **Goal:** Upload logs and monitor progress.
* **Component:** `JobControlComponent`
* **Features:**
    * **Upload:** Drag-and-drop zone for `.log` files.
    * **Control:** "Start Analysis" button (Disabled if 0 Trusted Nodes available).
    * **Feedback:** A terminal-like window showing logs: *"Verifying 192.168.0.101... Trust OK. Sending Chunk..."*

---

## 👩‍💻 Amritha (Worker & Security)
**Focus:** The "Muscle" (Execution) & Trust Responder.
**Directory:** `gridmind-agent/`

### ✅ Task 1: The Zero Trust Worker
* **Goal:** A smart listener that handles both Trust Handshakes and Job Execution.
* **File:** `worker.py` (Evolution of `trust_agent.py`)
* **Logic:**
    * **Token Gen:** Implement `SHA256("edge123" + time // 60)`.
    * **Listener:** Socket Server on Port 5555 handling JSON:
        * `IF cmd == "VERIFY_TRUST"`: Return Token.
        * `IF cmd == "ANALYZE"`: Run Parser (Task 2).

### ✅ Task 2: The Log Parser
* **Goal:** Actually process the data.
* **File:** `parser.py`
* **Logic:**
    * Function `scan_log(filepath)`:
    * Read line-by-line.
    * **Regex:** Count keywords like `SQL Syntax`, `error`, `404`, `root`.
    * **Output:** Save results to `results.json` (for Navneeth to fetch).

---

## 🧘‍♀️ Afrina (Health & Stability - Low Severity)
**Focus:** System Health & Test Data.
**Directory:** `gridmind-agent/` & `scripts/`

### ✅ Task 1: Idle Detection
* **Goal:** Prevent overloading student laptops.
* **File:** `health_check.py`
* **Logic:**
    * Function `is_idle()`:
    * Check CPU load (`os.getloadavg()`).
    * Return `True` only if Load < 20%.

### ✅ Task 2: Test Data Generator
* **Goal:** Create fake logs for offline testing.
* **File:** `scripts/generate_logs.py`
* **Logic:**
    * Create a 50MB text file.
    * Insert random "ATTACK" keywords at random intervals.
