import re
import os

# Pre-compiled Regex for performance
SIGNATURES = {
    "SQL_Injection": re.compile(r"(SELECT|UNION|INSERT|DELETE|' OR '1'='1|--|#)", re.IGNORECASE),
    "XSS_Attack": re.compile(r"(<script>|alert\(|%3Cscript%3E)", re.IGNORECASE),
    "Brute_Force": re.compile(r"(401|Failed password|invalid user|Login failed)", re.IGNORECASE),
    "Root_Access": re.compile(r"(sudo|root|access denied|permission denied)", re.IGNORECASE)
}

def scan_log(filepath):
    """Reads a file line-by-line and counts occurrences of threat patterns."""
    summary = {
        "filename": os.path.basename(filepath),
        "total_lines": 0,
        "threats_found": 0,
        "details": {k: 0 for k in SIGNATURES.keys()}
    }

    if not os.path.exists(filepath):
        return {"error": f"File {filepath} not found"}

    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as file:
            for line in file:
                summary["total_lines"] += 1
                for threat_type, pattern in SIGNATURES.items():
                    if pattern.search(line):
                        summary["details"][threat_type] += 1
                        summary["threats_found"] += 1
        return summary
    except Exception as e:
        return {"error": str(e)}