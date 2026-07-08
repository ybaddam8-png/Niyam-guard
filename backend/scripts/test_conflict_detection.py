"""
Usage: python3 scripts/test_conflict_detection.py <username> <password> [base_url]

Submits two rules on the SAME field_name via /check, with different effective_date_iso
values (both already in the past), then queries /conflicts to confirm the later-dated
rule was correctly identified as the one currently governing.
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
        print("Usage: python3 scripts/test_conflict_detection.py <username> <password> [base_url]")
        sys.exit(1)

    username, password = sys.argv[1], sys.argv[2]
    base_url = sys.argv[3] if len(sys.argv) > 3 else "http://127.0.0.1:8000"

    login = call("POST", f"{base_url}/auth/login", body={"username": username, "password": password})
    token = login["access_token"]
    print(f"Logged in as {username} (role={login['role']})")

    field_name = "income_certificate_validity_months_conflict_test"
    system = {"system_id": "conflict-test-portal", "system_type": "portal", "display_name": "Test Portal",
              "current_text": "Certificates valid up to 6 months are accepted.", "is_illustrative": True}

    rule_a = {
        "clause_id": "conflict-test-rule-A", "field_name": field_name,
        "old_value": "12 months", "new_value": "9 months",
        "effective_date": "1 January 2026", "effective_date_iso": "2026-01-01",
        "source_sentence": "Validity reduced from 12 to 9 months, effective 1 January 2026.",
        "confidence": "high", "confidence_reason": "Explicit dates and values stated.",
    }
    rule_b = {
        "clause_id": "conflict-test-rule-B", "field_name": field_name,
        "old_value": "9 months", "new_value": "6 months",
        "effective_date": "1 May 2026", "effective_date_iso": "2026-05-01",
        "source_sentence": "Validity further reduced from 9 to 6 months, effective 1 May 2026.",
        "confidence": "high", "confidence_reason": "Explicit dates and values stated.",
    }

    print("\n--- persisting rule A ---")
    call("POST", f"{base_url}/check", token=token, body={"rule": rule_a, "systems": [system]})
    print("done (should be no conflicts yet — rule A is the only one with this field_name)")

    print("\n--- persisting rule B (should trigger conflict detection against rule A) ---")
    call("POST", f"{base_url}/check", token=token, body={"rule": rule_b, "systems": [system]})
    print("done")

    conflicts = call("GET", f"{base_url}/conflicts?field_name={field_name}", token=token)
    print("\n--- /conflicts result ---")
    print(json.dumps(conflicts, indent=2))


if __name__ == "__main__":
    main()
