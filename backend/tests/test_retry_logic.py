"""
Proves app.llm_client.call_llm actually retries on 429 with real tenacity backoff timing,
and does NOT retry on a non-retryable error (401). The HTTP transport is mocked (respx) —
everything above the transport (tenacity, our error classification, retry count) is real.
"""
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["GEMINI_API_KEY"] = "fake-key-for-mocked-test"

import respx
import httpx
from app.llm_client import call_llm, LLMError

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"

print("=== Case 1: 429, 429, then 200 -> should succeed on 3rd real attempt ===")
with respx.mock(assert_all_called=True) as mock:
    route = mock.post(GEMINI_URL).mock(
        side_effect=[
            httpx.Response(429, text="rate limited"),
            httpx.Response(429, text="rate limited"),
            httpx.Response(200, json={"choices": [{"message": {"content": "ok on 3rd try"}}]}),
        ]
    )
    start = time.time()
    result = call_llm("system", "user")
    elapsed = time.time() - start
    print(f"result: {result!r}")
    print(f"call count: {route.call_count} (expect 3)")
    print(f"elapsed: {elapsed:.1f}s (expect >=6s: waits are ~2s then ~4s between attempts)")
    assert route.call_count == 3
    assert result == "ok on 3rd try"
    assert elapsed >= 5.5, "backoff didn't actually wait — retry would be fake without this"
print("PASS\n")

print("=== Case 2: 429 four times -> should give up after 3 attempts and raise ===")
with respx.mock(assert_all_called=True) as mock:
    route = mock.post(GEMINI_URL).mock(return_value=httpx.Response(429, text="rate limited"))
    try:
        call_llm("system", "user")
        raise AssertionError("should have raised")
    except LLMError as e:
        print(f"raised as expected: {e}")
    print(f"call count: {route.call_count} (expect 3, not 4 — stop_after_attempt(3))")
    assert route.call_count == 3
print("PASS\n")

print("=== Case 3: 401 (bad key) -> should NOT retry, fails on first attempt ===")
with respx.mock(assert_all_called=True) as mock:
    route = mock.post(GEMINI_URL).mock(return_value=httpx.Response(401, text="bad api key"))
    start = time.time()
    try:
        call_llm("system", "user")
        raise AssertionError("should have raised")
    except LLMError as e:
        print(f"raised as expected: {e}")
    elapsed = time.time() - start
    print(f"call count: {route.call_count} (expect 1 — not retryable)")
    print(f"elapsed: {elapsed:.2f}s (expect <1s — no backoff wait for non-retryable errors)")
    assert route.call_count == 1
    assert elapsed < 1.0
print("PASS\n")

print("ALL RETRY-LOGIC CHECKS PASSED")
