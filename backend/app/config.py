"""
Config is loaded entirely from environment variables. Never hardcode keys here.
Copy .env.example to .env and fill in real values before running.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Which provider to call for rule-delta extraction.
# "gemini" -> free tier via Gemini's OpenAI-compatible endpoint (recommended for hackathon budget)
# "anthropic" -> Claude API (use if you have credits)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").lower()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
# gemini-2.5-flash and gemini-2.5-flash-lite are free-tier eligible as of mid-2026.
# Verify current eligibility at https://ai.google.dev/gemini-api/docs/pricing before the event —
# Google has changed free-tier model eligibility multiple times in 2025-2026.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

# --- Database (Postgres) ---
# Full connection string, e.g. postgresql://user:pass@localhost:5432/niyamguard
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/niyamguard")

REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))

# --- Auth (real, per-user, JWT-based — replaces the MVP's shared-key stub) ---
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

# --- CORS ---
# Comma-separated list of allowed origins. Empty by default — you must explicitly opt in
# your frontend's real origin. This is the opposite default of the MVP's allow_origins=["*"].
_raw_origins = os.getenv("ALLOWED_ORIGINS", "")
ALLOWED_ORIGINS = [o.strip() for o in _raw_origins.split(",") if o.strip()]

# --- Rate limiting ---
# Applies to the LLM-calling endpoints specifically, to protect Gemini free-tier quota
# from being exhausted by either abuse or an accidental retry storm.
EXTRACTION_RATE_LIMIT = os.getenv("EXTRACTION_RATE_LIMIT", "5/minute")
