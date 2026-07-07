"""
Thin, provider-agnostic wrapper so extraction.py doesn't care which LLM is behind it.
Two real, verified request shapes are implemented:
  - Gemini via its OpenAI-compatible endpoint (POST {base}/chat/completions)
  - Anthropic Messages API (POST https://api.anthropic.com/v1/messages)
No SDK is used, just httpx, so there's nothing hidden in a library version.
"""
import json
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from app import config


class LLMError(RuntimeError):
    pass


class RetryableLLMError(LLMError):
    """429 (rate limit) or 5xx — worth retrying with backoff. Anything else (401, 400,
    malformed JSON) is NOT retryable and should surface to the caller immediately."""
    pass


_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


def _raise_for_status(resp: httpx.Response, provider: str) -> None:
    if resp.status_code in _RETRY_STATUS_CODES:
        raise RetryableLLMError(f"{provider} API error {resp.status_code} (retryable): {resp.text[:500]}")
    if resp.status_code != 200:
        raise LLMError(f"{provider} API error {resp.status_code}: {resp.text[:500]}")


def _call_gemini(system_prompt: str, user_prompt: str) -> str:
    if not config.GEMINI_API_KEY:
        raise LLMError("GEMINI_API_KEY is not set. Get a free key at https://aistudio.google.com/apikey")
    url = f"{config.GEMINI_BASE_URL}chat/completions"
    body = {
        "model": config.GEMINI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
    }
    headers = {
        "Authorization": f"Bearer {config.GEMINI_API_KEY}",
        "Content-Type": "application/json",
    }
    resp = httpx.post(url, json=body, headers=headers, timeout=config.REQUEST_TIMEOUT_SECONDS)
    _raise_for_status(resp, "Gemini")
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def _call_anthropic(system_prompt: str, user_prompt: str) -> str:
    if not config.ANTHROPIC_API_KEY:
        raise LLMError("ANTHROPIC_API_KEY is not set.")
    url = "https://api.anthropic.com/v1/messages"
    body = {
        "model": config.ANTHROPIC_MODEL,
        "max_tokens": 2000,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    headers = {
        "x-api-key": config.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    resp = httpx.post(url, json=body, headers=headers, timeout=config.REQUEST_TIMEOUT_SECONDS)
    _raise_for_status(resp, "Anthropic")
    data = resp.json()
    return "".join(block["text"] for block in data["content"] if block["type"] == "text")


# 3 attempts total, exponential backoff starting at 2s (2s, 4s, 8s ceiling at 10s) — matches
# the free-tier RPM windows (Gemini free tier resets within seconds, not minutes, for RPM).
# Only retries RetryableLLMError; a 401 (bad key) or 400 (bad request) fails fast instead of
# burning 3 attempts on something backoff can't fix.
@retry(
    retry=retry_if_exception_type(RetryableLLMError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=10),
    reraise=True,
)
def call_llm(system_prompt: str, user_prompt: str) -> str:
    """Routes to the configured provider. Returns raw text (caller parses JSON)."""
    if config.LLM_PROVIDER == "gemini":
        return _call_gemini(system_prompt, user_prompt)
    elif config.LLM_PROVIDER == "anthropic":
        return _call_anthropic(system_prompt, user_prompt)
    raise LLMError(f"Unknown LLM_PROVIDER: {config.LLM_PROVIDER}")


def extract_json(raw_text: str) -> dict:
    """LLMs often wrap JSON in ```json fences despite instructions. Strip defensively."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError as e:
        raise LLMError(f"Model did not return valid JSON: {e}\nRaw: {raw_text[:300]}")
