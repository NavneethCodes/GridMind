# 🛡️ GridMind: Distributed Cybersecurity Log Analysis

GridMind is a LAN-based distributed computing framework designed to parallelize the analysis of large cybersecurity logs using idle institutional hardware (Lab PCs). By splitting massive datasets and processing them across multiple nodes, GridMind reduces computation time while keeping sensitive data within the local network.

---

## 🌐 System Architecture
GridMind operates on a **Master-Worker** architecture over a local network managed by an **Archer AX10 Router**.

1.  **Master Node (Dell G16):** Orchestrates log chunking, job distribution via SSH/SCP, and result aggregation.
2.  **Worker Nodes (Lab PCs/Laptops):** Execute lightweight Python agents to parse log chunks and return anomaly reports.
3.  **Network:** 4 devices connected via LAN/Wi-Fi 6 (192.168.0.x range).

---

## 📂 Project Structure & Responsibilities

### 1. `gridmind-master/` ☕
**Assignee:** Navneeth
**Stack:** Spring Boot 3.x, Java 21, JSch (SSH)
* **Tasks:** * Develop the **Log Chunker** to split files into N parts.
    * Manage the **Task Registry** (H2/SQLite) to track worker status.
    * Implement **SCP/SSH logic** to push scripts and data to workers.

### 2. `gridmind-ui/` 🅰️
**Assignee:** Adish
**Stack:** Angular 18+, Tailwind CSS, Chart.js
* **Tasks:** * Build the **Command Center Dashboard** to monitor 4 worker nodes.
    * Create **Real-time Progress Bars** for log processing.
    * Visualize **Threat Analytics** (Pie charts and Highlighted Tables).

### 3. `gridmind-agent/` 🐍
**Assignee:** Afrina
**Stack:** Python 3.13, OS, Paramiko
* **Tasks:** * Develop the **Regex-based Parser** to scan chunks for security threats.
    * Implement **Idle Detection** to ensure minimal impact on worker PCs.
    * Handle **Result Signal Back** to the Master node.

### 4. `gridmind-analysis/` 🧠
**Assignee:** Amritha
**Stack:** Python, Scikit-learn, Pandas
* **Tasks:** * Build the **Anomaly Scoring Logic** (e.g., Isolation Forest or Pattern Matching).
    * Perform **Benchmarking** (Compare Single PC vs. 4-Node Grid performance).
    * Maintain project **Documentation** and Final Report.

---

## 🛠️ Infrastructure Setup (Lead)
* **OS:** Ubuntu 25.04 (Plucky Puffin)
* **Router:** Archer AX10 (Static IPs: 192.168.0.100 - 104)
* **Hardware:** Dell G16 (Master) + 3 Worker Nodes

---

## 🚀 Getting Started

1.  **Clone the Repo:**
    ```bash
    git clone <your-repo-url>
    cd GridMind
    ```

2.  **Environment Setup:**
    * **Backend:** Install OpenJDK 21.
    * **Frontend:** Install Node.js v18+ and `npm install -g @angular/cli`.
    * **Agent:** Ensure Python 3.x is installed on all worker nodes.

3.  **SSH Configuration:**
    Ensure the Master node has the Public SSH keys of all Worker nodes added to `~/.ssh/authorized_keys` for passwordless communication.

---

## 📅 Roadmap
- [x] **Phase 1:** Idea Finalization & LAN Setup.
- [ ] **Phase 2:** Core Implementation (Chunking, Distribution, Parsing).
- [ ] **Phase 3:** AI Enhancement & Dashboard Integration.

---
**Lead Note:** Keep your commits clean. Use branch names like `feature/navneeth-scheduler` or `feature/adish-ui`.
