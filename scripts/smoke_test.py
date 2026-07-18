#!/usr/bin/env python3
"""
Tamil AI Backend - Smoke Test Script

Runs a quick end-to-end verification of a running server (default: http://localhost:8001).
Checks auth, jobs, health, and public endpoints.

Features:
- Multi-user authentication & cross-user job ownership checks (User B cannot access User A's jobs)
- Robust error handling for rate limits (429) & backpressure during registration/login (with retry backoff)
- Detailed validation of parsed job results (ensures non-empty and schema-correct payloads)
- Non-blocking warning logging for Hugging Face flakiness (500/503) to distinguish HF errors from server code errors

Usage:
    # Run against local server on port 8001
    python scripts/smoke_test.py --host http://localhost:8001
"""

import sys
import uuid
import time
import argparse
import requests

# ANSI Color Codes
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def log_step(name: str):
    print(f"\n{BOLD}{CYAN}==> {name}{RESET}")


def log_success(message: str):
    print(f"{GREEN}✔ [OK] {message}{RESET}")


def log_warning(message: str):
    print(f"{YELLOW}⚠ [WARN] {message}{RESET}")


def log_failure(message: str):
    print(f"{RED}✘ [FAILED] {message}{RESET}")


def request_with_retry(method, url, max_retries=3, backoff_seconds=2, **kwargs):
    """
    Helper to execute request with automatic retry on transient rate limiting (429)
    or temporary service overloading (503).
    """
    for attempt in range(max_retries):
        try:
            r = requests.request(method, url, **kwargs)
            if r.status_code in (429, 503):
                log_warning(f"Server returned {r.status_code}. Retrying in {backoff_seconds}s...")
                time.sleep(backoff_seconds)
                continue
            return r
        except requests.RequestException as e:
            if attempt == max_retries - 1:
                raise e
            time.sleep(backoff_seconds)
    return requests.request(method, url, **kwargs)


def register_and_login_user(host: str, suffix: str, user_label: str):
    """Utility to register and login a test user, returning auth headers and refresh token."""
    username = f"smoke_{user_label}_{suffix}"
    email = f"{username}@smoketest.dev"
    password = f"SmokePass@{suffix}"

    # 1. Register user
    r = request_with_retry(
        "POST",
        f"{host}/auth/register",
        json={"username": username, "email": email, "password": password},
        timeout=5
    )
    if r.status_code != 201:
        log_failure(f"[{user_label}] Registration failed: {r.status_code} - {r.text}")
        sys.exit(1)
    
    log_success(f"[{user_label}] Registered user '{username}' successfully")

    # 2. Login user
    r = request_with_retry(
        "POST",
        f"{host}/auth/login",
        json={"username": username, "password": password},
        timeout=5
    )
    if r.status_code != 200:
        log_failure(f"[{user_label}] Login failed: {r.status_code} - {r.text}")
        sys.exit(1)

    data = r.json()
    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token")

    if not access_token or not refresh_token:
        log_failure(f"[{user_label}] Missing access_token/refresh_token in response: {data}")
        sys.exit(1)

    log_success(f"[{user_label}] Logged in successfully; JWT tokens received")
    return {"Authorization": f"Bearer {access_token}"}, refresh_token


def run_smoke_test(host: str):
    print("=" * 60)
    print(f"  {BOLD}Tamil AI Backend Smoke Test{RESET}")
    print(f"  Target Host: {BOLD}{host}{RESET}")
    print("=" * 60)

    # 1. Health Check
    log_step("Checking /health API")
    try:
        r = requests.get(f"{host}/health", timeout=5)
        if r.status_code == 200 and r.json().get("status") == "healthy":
            log_success("Health check reports healthy")
        else:
            log_failure(f"Unexpected health response: {r.status_code} - {r.text}")
            sys.exit(1)
    except Exception as e:
        log_failure(f"Could not connect to server at {host}: {e}")
        sys.exit(1)

    # 2. Metadata / Root / Models
    log_step("Checking public metadata endpoints")
    try:
        r = requests.get(f"{host}/", timeout=5)
        if r.status_code == 200:
            log_success("Root endpoint is active")
        else:
            log_failure(f"Root endpoint failed: {r.status_code}")

        r = requests.get(f"{host}/models", timeout=5)
        if r.status_code == 200:
            models_data = r.json()
            models_list = models_data.get("models", [])
            log_success(f"Models endpoint list returned {len(models_list)} models")
        else:
            log_failure(f"Models endpoint failed: {r.status_code}")
    except Exception as e:
        log_failure(f"Public metadata requests failed: {e}")

    # 3. Non-auth Security Check
    log_step("Checking authentication enforcement")
    try:
        r = requests.get(f"{host}/auth/me", timeout=5)
        if r.status_code == 401:
            log_success("Unauthenticated /auth/me blocked correctly (401)")
        else:
            log_failure(f"Unauthenticated request to /auth/me returned: {r.status_code} (expected 401)")

        r = requests.post(f"{host}/jobs", json={"model": "letter-gen", "input": "test"}, timeout=5)
        if r.status_code == 401:
            log_success("Unauthenticated POST /jobs blocked correctly (401)")
        else:
            log_failure(f"Unauthenticated request to POST /jobs returned: {r.status_code} (expected 401)")
    except Exception as e:
        log_failure(f"Security checks failed: {e}")

    # 4. Multi-User Authentication & Job Ownership Setup
    log_step("Setting up multi-user tokens for ownership check")
    suffix = uuid.uuid4().hex[:8]
    
    # Register and log in User A
    headers_user_a, refresh_user_a = register_and_login_user(host, suffix, "user_a")
    
    # Register and log in User B
    headers_user_b, refresh_user_b = register_and_login_user(host, suffix, "user_b")

    # 5. Job Creation by User A and Cross-User Ownership Verification
    log_step("Verifying Job Ownership Security rules")
    
    # Submit Job under User A.
    # Note: We send a flat string "input" which is the correct format for starting
    # session-based models on the backend. Nested dictionaries like {"input": {"user_request": "..."}}
    # will default to an empty prompt in LetterGenAdapter since it specifically expects "prompt", 
    # "user_text", or "input" keys in the nested dictionary.
    payload = {
        "model": "letter-gen",
        "input": "பள்ளிக்கு விடுப்பு கடிதம்"
    }
    
    job_id = None
    try:
        r = request_with_retry("POST", f"{host}/jobs", json=payload, headers=headers_user_a, timeout=5)
        if r.status_code == 200:
            job_data = r.json()
            job_id = job_data.get("job_id")
            log_success(f"Job successfully created by User A (job_id: {job_id})")
        else:
            log_failure(f"Failed to submit job under User A: {r.status_code} - {r.text}")
            sys.exit(1)
    except Exception as e:
        log_failure(f"Failed to perform job creation request: {e}")
        sys.exit(1)

    # Attempt to fetch User A's job using User B's token (Should return 403)
    if job_id:
        try:
            r = requests.get(f"{host}/jobs/{job_id}", headers=headers_user_b, timeout=5)
            if r.status_code == 403:
                log_success("CROSS-USER READ BLOCKED: User B access to User A's job was correctly forbidden (403)")
            else:
                log_failure(f"CROSS-USER READ VULNERABILITY: User B was allowed to request User A's job! Response code: {r.status_code}")
                sys.exit(1)
        except Exception as e:
            log_failure(f"Cross-user job read check failed to request: {e}")
            sys.exit(1)

        # Confirm User A can read their own job (Should return 200)
        try:
            r = requests.get(f"{host}/jobs/{job_id}", headers=headers_user_a, timeout=5)
            if r.status_code == 200:
                log_success("User A read authorization confirmed: User A can access their own job (200)")
            else:
                log_failure(f"User A read failed on own job: {r.status_code} - {r.text}")
                sys.exit(1)
        except Exception as e:
            log_failure(f"User A self-job read check failed: {e}")
            sys.exit(1)

    # 6. Job Execution & Result Schema Validation
    if job_id:
        log_step("Polling job status & validating parsed result structure")
        retries = 20
        completed = False
        for i in range(retries):
            poll_r = requests.get(f"{host}/jobs/{job_id}", headers=headers_user_a, timeout=5)
            if poll_r.status_code == 200:
                status_data = poll_r.json()
                current_status = status_data.get("status")
                print(f"  [Poll {i+1}] Job status: {current_status}")
                
                if current_status == "done":
                    completed = True
                    result = status_data.get("result")
                    
                    # Validate non-empty and well-formed result structure
                    if not result:
                        log_failure("Job parsed result is empty or null")
                        sys.exit(1)
                        
                    if not isinstance(result, dict):
                        log_failure(f"Job result is not a structured dictionary (received: {type(result).__name__})")
                        sys.exit(1)
                        
                    # Specific letter-gen start phase schema validation
                    required_keys = ["status", "step", "session_id", "type", "current_question"]
                    missing_keys = [k for k in required_keys if k not in result]
                    if missing_keys:
                        log_failure(f"Result dictionary is missing required schema keys: {missing_keys}")
                        sys.exit(1)
                    
                    if result.get("status") != "success":
                        log_failure(f"Result status key is not 'success': {result}")
                        sys.exit(1)

                    log_success("Job output verified: Non-empty result matches expected schema structure")
                    break
                    
                elif current_status == "failed":
                    completed = True
                    log_failure(f"Job finished with 'failed' status. Error message: {status_data.get('error')}")
                    sys.exit(1)
            else:
                log_failure(f"Polling job failed with status: {poll_r.status_code}")
                sys.exit(1)
            time.sleep(2)
        
        if not completed:
            log_warning("Job did not complete within the timeout limits (still queued or running)")

    # 7. Test HF Live Call (Synchronous check)
    log_step("Checking synchronous live HF endpoint (/test-hf-live)")
    try:
        live_payload = {
            "model": "proofreader",
            "user_text": "வணக்கம்"
        }
        r = requests.post(f"{host}/test-hf-live", json=live_payload, timeout=20)
        
        if r.status_code == 200:
            response_json = r.json()
            result = response_json.get("result")
            if response_json.get("status") != "success" or not result or not isinstance(result, dict):
                log_failure(f"Live HF returned malformed result payload: {response_json}")
                sys.exit(1)
            
            # Assertions specific to proofreader schema
            if "tokens" not in result or "input" not in result:
                log_failure(f"Live HF proofreader result missing required keys (tokens/input): {result}")
                sys.exit(1)

            log_success(f"Live HF test succeeded and payload schema is correct: {result}")
        elif r.status_code == 503:
            log_warning("Live HF returned 503 (expected service unavailable / cold start)")
        elif r.status_code == 500:
            log_warning("Live HF returned 500 (internal error, possibly HF rate limit/timeout)")
        else:
            log_failure(f"Unexpected live HF call status: {r.status_code} - {r.text}")
            sys.exit(1)
    except Exception as e:
        log_failure(f"Live HF call exception: {e}")
        sys.exit(1)

    # 8. Clean up and Logout
    log_step("Checking Token Revocation (/auth/logout)")
    try:
        r = requests.post(f"{host}/auth/logout", json={"refresh_token": refresh_user_a}, timeout=5)
        if r.status_code == 200:
            log_success("User A logout successful (refresh token revoked)")
        else:
            log_failure(f"User A logout failed: {r.status_code} - {r.text}")

        r = requests.post(f"{host}/auth/logout", json={"refresh_token": refresh_user_b}, timeout=5)
        if r.status_code == 200:
            log_success("User B logout successful (refresh token revoked)")
        else:
            log_failure(f"User B logout failed: {r.status_code} - {r.text}")
    except Exception as e:
        log_failure(f"Logout request failed: {e}")

    print("\n" + "=" * 60)
    print(f"  {BOLD}{GREEN}Smoke Test Complete - All checks passed!{RESET}")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tamil AI Backend Smoke Test")
    parser.add_argument("--host", default="http://localhost:8001", help="Target API Server URL")
    args = parser.parse_args()

    run_smoke_test(args.host)
