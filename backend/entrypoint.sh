#!/bin/sh
set -e

echo "Waiting for Postgres to accept connections..."
python3 - << 'PYEOF'
import os, sys, time
import psycopg2

url = os.environ["DATABASE_URL"]
for attempt in range(30):
    try:
        conn = psycopg2.connect(url)
        conn.close()
        print("Postgres is ready.")
        sys.exit(0)
    except Exception as e:
        print(f"  not ready yet (attempt {attempt + 1}/30): {e}")
        time.sleep(2)
print("Postgres never became ready after 60s — exiting.")
sys.exit(1)
PYEOF

echo "Running database migrations..."
alembic upgrade head

echo "Starting server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
