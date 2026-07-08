"""
Usage: python3 scripts/test_scale_view.py <username> <password> [base_url]

Logs in, POSTs a single rule checked against 4 systems split across 2 entities
(one entity deliberately out of sync to trigger ripple), then GETs /scale-view
for that rule and prints the per-entity breakdown.
"""
import sys
import json
import urllib.request
import urllib.error


def call(method, url, token=None, body=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code} error body:", e.read().decode("utf-8"))
        sys.exit(1)


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 scripts/test_scale_view.py <username> <password> [base_url]")
        sys.exit(1)

    username, password = sys.argv[1], sys.argv[2]
    base_url = sys.argv[3] if len(sys.argv) > 3 else "http://127.0.0.1:8000"

    login = call("POST", f"{base_url}/auth/login", body={"username": username, "password": password})
    token = login["access_token"]
    print(f"Logged in as {username} (role={login['role']})")

    rule = {
        "clause_id": "test-scale-view-1",
        "field_name": "income_certificate_validity_months",
        "old_value": "12 months",
        "new_value": "6 months",
        "effective_date": "2026-04-01",
        "source_sentence": "Income certificates must be valid within 6 months of issue.",
        "confidence": "high",
        "confidence_reason": "Explicit numeric change stated directly in the circular.",
    }

    systems = [
        {"system_id": "warangal-portal", "system_type": "portal", "display_name": "Warangal Portal",
         "current_text": "Certificates valid up to 12 months are accepted.", "is_illustrative": True,
         "scheme_id": "income-certificate-scheme", "entity_label": "District: Warangal"},
        {"system_id": "warangal-sop", "system_type": "sop", "display_name": "Warangal Officer SOP",
         "current_text": "Officers should accept certificates within 12 months.", "is_illustrative": True,
         "scheme_id": "income-certificate-scheme", "entity_label": "District: Warangal"},
        {"system_id": "nizamabad-portal", "system_type": "portal", "display_name": "Nizamabad Portal",
         "current_text": "Certificates valid up to 6 months are accepted.", "is_illustrative": True,
         "scheme_id": "income-certificate-scheme", "entity_label": "District: Nizamabad"},
        {"system_id": "nizamabad-sop", "system_type": "sop", "display_name": "Nizamabad Officer SOP",
         "current_text": "Officers should accept certificates within 6 months.", "is_illustrative": True,
         "scheme_id": "income-certificate-scheme", "entity_label": "District: Nizamabad"},
    ]

    check_result = call("POST", f"{base_url}/check", token=token, body={"rule": rule, "systems": systems})
    print("\n--- /check result ---")
    print(json.dumps(check_result, indent=2))

    scale = call("GET", f"{base_url}/scale-view/{rule['clause_id']}", token=token)
    print("\n--- /scale-view result ---")
    print(json.dumps(scale, indent=2))


if __name__ == "__main__":
    main()
