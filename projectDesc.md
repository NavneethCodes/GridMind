SSSSSSS# 🛡️ GridMind: Distributed Cybersecurity Intelligence Grid

![Status](https://img.shields.io/badge/Status-Phase%202:%20Resilience-orange?style=flat-square)
![Java](https://img.shields.io/badge/Backend-Spring%20Boot%203-green?style=flat-square)
![Security](https://img.shields.io/badge/Security-Zero%20Trust%20Architecture-red?style=flat-square)
![Network](https://img.shields.io/badge/Deployment-Air--Gapped%20LAN-blue?style=flat-square)

> **The Problem:** Modern cybersecurity logs (Apache Access Logs, Syslogs) generate terabytes of data daily. Analyzing this on a single machine is slow; analyzing it on the cloud is expensive and insecure.
>
> **The Solution:** GridMind turns an existing, idle Computer Lab into a high-performance **Distributed Compute Cluster** without requiring internet access or cloud infrastructure.

---

## 🏗️ Technical Architecture

GridMind is built on a **Resilient Master-Worker Topology**. Unlike traditional clusters, GridMind assumes the network is unreliable and the nodes are untrusted until proven otherwise.

### 1. The Master Node (Orchestrator)
The "Brain" of the operation. It does not process data; it manages the state of the grid.
* **Tech Stack:** Java 21, Spring Boot 3.2, Redis (State), H2 (History).
* **Key Modules:**
  * **`JobDispatcher`:** Slices massive log files (e.g., 1GB) into 50MB "Chunks" using efficient file streaming.
  * **`ZeroTrustService`:** Implements a challenge-response mechanism. It generates a time-based SHA-256 token that changes every minute. Workers must sign their requests with this token.
  * **`RecoveryService`:** A self-healing engine. On startup, it queries Redis for "Known Nodes," checks their health via Socket/ICMP, and re-establishes state without human intervention.

### 2. The Worker Node (Agent)
The "Muscle." A lightweight agent running on lab PCs.
* **Tech Stack:** Python 3.12 (Standard Library Only - No `pip install` required for easy deployment).
* **Key Capabilities:**
  * **Regex Engine:** Compiles optimized Regular Expressions to hunt for SQL Injection (`' OR 1=1`), XSS, and Brute Force patterns.
  * **Store-and-Forward Cache:** If the Master is unreachable (network failure), the Agent serializes results to `JSON` on disk. It enters a "Retry Loop" and automatically syncs data when the connection is restored.

### 3. The Network Layer (Gatekeeper)
The "Shield." Manages physical access to the grid.
* **Tech Stack:** Python Flask, `dnsmasq`, `iptables`.
* **Workflow:**
  1.  **Intercept:** New devices are assigned an IP but blocked from the Grid.
  2.  **Captive Portal:** DNS spoofs all requests to the **Angular Landing Page**.
  3.  **Admission:** Upon "Join," the MAC address is allowlisted in `iptables`.

---

## 🔐 Deep Dive: Zero Trust Protocol
GridMind does not trust a device just because it is on the LAN. Every sensitive operation requires cryptographic proof.

1.  **The Handshake:**
  * Master & Worker share a pre-configured `SECRET_KEY` (embedded in the binary).
  * **Token Generation:** `Token = SHA256(SECRET_KEY + CURRENT_TIME_MINUTE)`
2.  **The Verification:**
  * Worker sends `POST /api/results` with Header `X-Grid-Auth: <Token>`.
  * Master independently calculates the expected token.
  * **Match?** Process Data. **Mismatch?** Ban IP immediately (Potential Intruder).

---

## ⚡ Deep Dive: Resilience Engine (Fault Tolerance)
How GridMind handles the "Unplugged Cable" scenario:

### Scenario: Master Node Crash / Restart
1.  **State Freeze:** Active jobs in Java Memory are lost, but **Redis** retains the `worker:192.168.1.X` registry.
2.  **Reboot:** Spring Boot initializes the `RecoveryService`.
3.  **Scan:** The service pulls all keys matching `worker:*` from Redis.
4.  **Probe:** It sends a `CMD:STATUS` packet to every registered IP.
5.  **Re-Sync:** Workers reply with their current load and any cached results. The Dashboard updates instantly.

---

## 🔌 API Specification (Internal REST Grid)

The Master Node exposes a secure REST API for Workers and the Dashboard.

| Method | Endpoint | Description | Payload |
| :--- | :--- | :--- | :--- |
| **POST** | `/api/register` | Worker announces availability. | `{ "ip": "192.168.1.5", "cores": 8 }` |
| **GET** | `/api/heartbeat` | Dashboard polls for grid status. | *None* |
| **POST** | `/api/jobs/chunk` | Worker requests a new data chunk. | `{ "workerId": "node-01" }` |
| **POST** | `/api/sync/offline-dump` | **(Resilience)** Worker uploads cached data after reconnection. | `[ { "jobId": 101, "threats": [...] } ]` |

---

## 🛠️ Deployment Instructions

### Prerequisites
* **Master:** Ubuntu 24.04+, Java 21, Redis Server (`sudo apt install redis-server`).
* **Workers:** Any OS with Python 3 installed.
* **Network:** An isolated Router or Switch.

### 1. Start the Master (The Brain)
```bash
cd gridmind-master
mvn clean install
mvn spring-boot:run
# Server starts on port 8080. Zero Trust engine initializes.
```
### 2. Start the Network Controller (The Gatekeeper)
```bash
cd gridmind-net
sudo python3 controller.py
# Captive Portal active on Port 80.
```
### 3. Deploy a Worker (The Muscle)
```bash
cd gridmind-agent
python3 worker.py
# Agent connects to Master and awaits instructions.
```