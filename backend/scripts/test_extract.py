"""
Usage: python3 scripts/test_extract.py <path_to_circular.txt> <api_token> [base_url]

Reads a plain text file (line breaks and all — no manual escaping needed) and POSTs it
to /circulars/extract correctly. Pure stdlib (urllib + json) — no extra pip install.
"""
import sys
import json
import urllib.request
import urllib.error


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 scripts/test_extract.py <path_to_circular.txt> <api_token> [base_url]")
        sys.exit(1)

    file_path = sys.argv[1]
    token = sys.argv[2]
    base_url = sys.argv[3] if len(sys.argv) > 3 else "http://127.0.0.1:8000"

    with open(file_path, "r", encoding="utf-8") as f:
        circular_text = f.read()

    body = json.dumps({"circular_text": circular_text}).encode("utf-8")

    req = urllib.request.Request(
        f"{base_url}/circulars/extract",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )

    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            print(f"Status: {resp.status}\n")
            print(json.dumps(result, indent=2, ensure_ascii=False))
    except urllib.error.HTTPError as e:
        print(f"Status: {e.code}\n")
        print(e.read().decode("utf-8"))


if __name__ == "__main__":
    main()
