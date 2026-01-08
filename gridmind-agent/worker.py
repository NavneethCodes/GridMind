import socket
import hashlib
import time
import json
import threading
from parser import scan_log

# Configuration
SECRET_KEY = "edge123"  # Must match Navneeth's SECRET_KEY
PORT = 5555

def generate_trust_token():
    """Generates a SHA256 token based on the shared key and current minute."""
    timestamp_minutes = int(time.time() // 60)
    data = f"{SECRET_KEY}{timestamp_minutes}"
    return hashlib.sha256(data.encode()).hexdigest()

def handle_request(conn, addr):
    """Processes incoming JSON commands from the Master Node."""
    try:
        raw_data = conn.recv(1024).decode('utf-8')
        if not raw_data:
            return

        request = json.loads(raw_data)
        command = request.get("cmd")

        # Handshake: Master verifies if this worker is genuine
        if command == "VERIFY_TRUST":
            token = generate_trust_token()
            response = {"status": "TRUSTED", "token": token}
            conn.send(json.dumps(response).encode('utf-8'))
            print(f"[!] Trust handshake verified for {addr}")

        # Execution: Master sends a file path for analysis
        elif command == "ANALYZE":
            filepath = request.get("filepath")
            print(f"[*] Analyzing: {filepath}")

            # Run the parser logic
            results = scan_log(filepath)

            # Save results locally to results.json as required
            with open("results.json", "w") as f:
                json.dump(results, f, indent=4)

            conn.send(json.dumps({"status": "COMPLETED", "output": "results.json"}).encode('utf-8'))

    except Exception as e:
        print(f"[ERROR] {e}")
    finally:
        conn.close()

def start_agent():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Allow port reuse to prevent 'Address already in use' errors
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', PORT))
    server.listen(5)
    print(f"[GRIDMIND AGENT] Muscle is active on port {PORT}...")

    while True:
        conn, addr = server.accept()
        # Threading ensures the agent can handle trust checks while parsing
        client_thread = threading.Thread(target=handle_request, args=(conn, addr))
        client_thread.start()

if __name__ == "__main__":
    start_agent()