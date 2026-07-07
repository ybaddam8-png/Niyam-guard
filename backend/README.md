# NiyamGuard AI — Backend (Production hardening pass)

Real Postgres, real per-user JWT auth with roles, rate limiting, retry/backoff on the
LLM call, structured logging, restricted CORS. This supersedes the earlier SQLite +
shared-key MVP build.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Postgres — install locally or point DATABASE_URL at any Postgres instance
sudo apt-get install -y postgresql postgresql-contrib   # if running locally
sudo service postgresql start
sudo -u postgres createdb niyamguard
sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'yourpassword';"

cp .env.example .env
# edit .env:
#  - DATABASE_URL (matches the createdb/password above)
#  - JWT_SECRET_KEY: python3 -c "import secrets; print(secrets.token_hex(32))"
#  - GEMINI_API_KEY: free key at https://aistudio.google.com/apikey
#  - ALLOWED_ORIGINS: your real frontend origin(s)
```

## Run migrations, then the server

```bash
alembic upgrade head
python3 -m scripts.create_admin youradminname yourpassword   # bootstrap the first account
uvicorn app.main:app --reload --port 8000
```

Open http://127.0.0.1:8000/docs for interactive Swagger UI. Click "Authorize", log in via
`/auth/login` first to get a token, then paste `Bearer <token>` to test protected routes.

## Verify everything works

```bash
python3 tests/test_production.py   # full stack against real Postgres, real bcrypt/JWT/RBAC/rate-limiting
python3 tests/test_retry_logic.py  # proves LLM retry/backoff actually waits and actually gives up
```

Only the actual external LLM HTTP call is mocked in these tests (clearly labeled in each
file) — everything else, including the database, runs for real.

## Architecture

```
Postgres  <--SQLAlchemy-->  app/models.py  <--  app/main.py (FastAPI routes)
                                                     |
                                    app/auth.py (JWT + RBAC) ---- app/security.py (bcrypt + JWT)
                                                     |
                            app/extraction.py --> app/llm_client.py (Gemini/Anthropic, retried)
                                                     |
                        app/diffing.py + app/graph.py (pure logic, no I/O, fully unit-testable)
                                                     |
                              app/audit_service.py (hash-chained, Postgres-backed)
```

## Auth & Roles

Real per-user accounts, not a shared key. Three roles, hierarchical:

| Role | Can do |
|---|---|
| `viewer` | read `/audit`, `/audit/verify` |
| `reviewer` | + run extraction, `/check`, record `/approvals` |
| `admin` | + create other users via `/auth/users` |

No public registration endpoint — create the first admin with `scripts/create_admin.py`,
everyone else via `/auth/users` (admin-only).

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | none | liveness check |
| POST | `/auth/login` | none | exchange username/password for a JWT |
| POST | `/auth/users` | admin | create a reviewer/viewer/admin account |
| POST | `/circulars/extract` | reviewer+ | raw text -> RuleDelta list, persisted, rate-limited |
| POST | `/circulars/extract-pdf` | reviewer+ | same, from an uploaded PDF |
| POST | `/check` | reviewer+ | rule + systems -> ranked flags, persisted |
| POST | `/approvals` | reviewer+ | log a human approval decision (never auto-sends) |
| GET | `/audit` | viewer+ | full audit trail |
| GET | `/audit/verify` | viewer+ | recompute the hash chain, detect tampering |

## What changed from the MVP build, and why

| MVP | Production | Why |
|---|---|---|
| SQLite, flat audit-log-only storage | Postgres + SQLAlchemy + Alembic, real relational schema (circulars, rule_deltas, dependent_systems, mismatch_flags, approvals, users, audit_log) | Concurrent writers, real backups (`pg_dump`), queryable history |
| Shared API key | Per-user JWT with 3 roles | Audit log `actor` field is now tied to a real account, not "whoever has the key" |
| No retry on LLM calls | tenacity: 3 attempts, exponential backoff, only on 429/5xx | Gemini free tier WILL rate-limit during a live demo — verified this actually waits and actually gives up (see test) |
| CORS wide open | Restricted to `ALLOWED_ORIGINS` | Wide-open CORS on a government-data API is a real, not theoretical, risk |
| No rate limiting | slowapi, configurable, applied to LLM-calling routes | Protects free-tier quota from being burned by retries or abuse |
| Free-text logging | Structured JSON logs + request-id correlation | A failure mid-demo is traceable instead of a mystery |

## Honest gaps still open (not hidden — these are real next steps)

- **Passlib was dropped, not "fixed."** It hit a real, reproducible crash against modern
  `bcrypt` (passlib 1.7.4 reads `bcrypt.__about__.__version__`, removed in bcrypt 4.1+,
  and passlib hasn't had a release since 2020 to catch up). We call `bcrypt` directly
  instead — this is the more robust choice, not a workaround to revisit.
- **No refresh tokens** — JWTs expire after `ACCESS_TOKEN_EXPIRE_MINUTES` (default 60)
  and the user just has to log in again. Fine for a single demo session, not for a
  real multi-day deployment.
- **No secrets manager** — `.env` is still a flat file. Wiring in AWS Secrets Manager /
  HashiCorp Vault / similar is a real next step for an actual government deployment,
  not done here.
- **No containerization yet, no CI, no load testing, no backup/DR runbook** — these were
  explicitly deferred to Phase 2/3 (see chat) and are not silently skipped.
- **The in-sync/out-of-sync check is still string-similarity, not semantic** — same
  limitation as the MVP, unchanged in this pass.
- **Multilingual extraction still untested against a real regional-language circular**
  and the extraction prompt itself has never been run against a real LLM in this
  sandbox (no API key here) — that remains the single biggest real-world unknown.
