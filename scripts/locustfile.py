"""
Locust load-testing script for the Tamil AI Backend API.

Usage:
    # Install locust first (not in production requirements):
    #   pip install locust

    # Run against a local dev server:
    locust -f scripts/locustfile.py --host http://localhost:8001

    # Headless run (10 users, spawn rate matching 2 ramp-ups, run for 5 min):
    locust -f scripts/locustfile.py --host http://localhost:8001 \
           --users 10 --spawn-rate 5 --run-time 5m --headless

    # Then open the Locust web UI at http://localhost:8089
"""

import random
import string
import time
import logging

from locust import HttpUser, task, between, tag, events

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────
# Set these via environment variables or modify directly for your test.
DEFAULT_TEST_USER_PREFIX = "locust_user_"
DEFAULT_TEST_PASSWORD = "LocustTest@123"

# Models currently loaded on the local server. Keep this list in sync with
# whatever is actually running — models not in this list will 500/503 on
# /jobs and /test-hf-live, which just adds noise to the report rather than
# telling you anything about real performance.
AVAILABLE_MODELS = [
    "mcq-gen",
    "email-gen",
    "letter-gen",
    "proofreader",
]

# Sample Tamil prompts per model — realistic inputs for load testing.
SAMPLE_INPUTS = {
    "letter-gen": {
        "input": {
            "user_request": "பள்ளிக்கு விடுப்பு கடிதம் எழுதுங்கள்"
        },
    },
    "paraphrase-gen": {
        "input": {
            "text": "தமிழ் ஒரு பழமையான மொழி. இது இரண்டாயிரம் ஆண்டுகளுக்கும் மேலான வரலாற்றைக் கொண்டது."
        },
    },
    "mcq-gen": {
        "input": {
            "passage": (
                "தமிழ் இலக்கியம் மிகவும் பழமையானது. "
                "சங்க இலக்கியம் கி.மு. மூன்றாம் நூற்றாண்டிலிருந்து கி.பி. மூன்றாம் நூற்றாண்டு வரை "
                "எழுதப்பட்டது. இது பத்துப்பாட்டு, எட்டுத்தொகை என இரு பிரிவுகளாகப் பிரிக்கப்படுகிறது."
            )
        },
    },
    "tongue-twister": {
        "input": {
            "user_input": "கிளி"
        },
    },
    "poem-gen": {
        "input": {
            "topic": "இயற்கை அழகு"
        },
    },
    "email-gen": {
        "input": {
            "text": "நிறுவனத்திற்கு வேலை விண்ணப்பம் அனுப்ப மின்னஞ்சல் எழுதுங்கள்"
        },
    },
    "proofreader": {
        "input": {
            "word": "வணக்கம் நாண் நல்லா இருக்கேன்"
        },
    },
}


def _random_suffix(length: int = 8) -> str:
    """Generate a random alphanumeric suffix for unique usernames."""
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


# ─────────────────────────────────────────────────────────────────────
# Locust User Class
# ─────────────────────────────────────────────────────────────────────
class TamilAIUser(HttpUser):
    """
    Simulates a real user interacting with the Tamil AI Backend.

    Lifecycle:
      1. on_start  → register a unique user, login, store tokens.
      2. tasks     → weighted mix of API calls (jobs, polling, auth, etc.)
      3. on_stop   → logout to revoke the refresh token.
    """

    # Wait 1–3 seconds between each task to simulate realistic pacing.
    wait_time = between(1, 3)

    # ── Lifecycle ──────────────────────────────────────────────────

    def on_start(self):
        """Register a fresh user and log in to obtain auth tokens."""
        suffix = _random_suffix()
        self.username = f"{DEFAULT_TEST_USER_PREFIX}{suffix}"
        self.email = f"{self.username}@locusttest.dev"
        self.password = DEFAULT_TEST_PASSWORD
        self.access_token = None
        self.refresh_token = None
        self.submitted_job_ids = []  # Track jobs for polling

        self._register()
        self._login()

    def on_stop(self):
        """Logout to cleanly revoke the refresh token."""
        if self.refresh_token:
            self._logout()

    # ── Auth Helpers ───────────────────────────────────────────────

    def _auth_headers(self) -> dict:
        """Return Bearer token header for authenticated requests."""
        if self.access_token:
            return {"Authorization": f"Bearer {self.access_token}"}
        return {}

    def _register(self):
        """Register a new test user."""
        with self.client.post(
            "/auth/register",
            json={
                "username": self.username,
                "email": self.email,
                "password": self.password,
            },
            name="/auth/register",
            catch_response=True,
        ) as response:
            if response.status_code == 201:
                response.success()
            elif response.status_code == 400:
                # Username/email already exists — that's OK for re-runs
                response.success()
            else:
                response.failure(f"Registration failed: {response.status_code} {response.text}")

    def _login(self):
        """Login and store access + refresh tokens."""
        with self.client.post(
            "/auth/login",
            json={
                "username": self.username,
                "password": self.password,
            },
            name="/auth/login",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                data = response.json()
                self.access_token = data.get("access_token")
                self.refresh_token = data.get("refresh_token")
                response.success()
            else:
                response.failure(f"Login failed: {response.status_code} {response.text}")

    def _logout(self):
        """Revoke the refresh token (logout)."""
        self.client.post(
            "/auth/logout",
            json={"refresh_token": self.refresh_token},
            name="/auth/logout",
        )

    # ── Public Endpoints ───────────────────────────────────────────

    @tag("public")
    @task(5)
    def health_check(self):
        """GET /health — lightweight liveness probe."""
        self.client.get("/health", name="/health")

    @tag("public")
    @task(3)
    def get_root(self):
        """GET / — root status endpoint."""
        self.client.get("/", name="/")

    @tag("public")
    @task(3)
    def list_models(self):
        """GET /models — list available AI models."""
        self.client.get("/models", name="/models")

    # ── Auth Endpoints ─────────────────────────────────────────────

    @tag("auth")
    @task(2)
    def get_my_profile(self):
        """GET /auth/me — fetch current user profile."""
        self.client.get(
            "/auth/me",
            headers=self._auth_headers(),
            name="/auth/me",
        )

    @tag("auth")
    @task(2)
    def get_account_profile(self):
        """GET /auth/account — fetch account details."""
        self.client.get(
            "/auth/account",
            headers=self._auth_headers(),
            name="/auth/account",
        )

    @tag("auth")
    @task(1)
    def update_account_profile(self):
        """PUT /auth/account — update display name."""
        self.client.put(
            "/auth/account",
            headers=self._auth_headers(),
            json={"display_name": f"Locust User {_random_suffix(4)}"},
            name="/auth/account [PUT]",
        )

    @tag("auth")
    @task(1)
    def refresh_tokens(self):
        """POST /auth/refresh — rotate tokens (token refresh flow)."""
        if not self.refresh_token:
            return

        with self.client.post(
            "/auth/refresh",
            json={"refresh_token": self.refresh_token},
            name="/auth/refresh",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                data = response.json()
                self.access_token = data.get("access_token")
                self.refresh_token = data.get("refresh_token")
                response.success()
            else:
                # Token was already rotated or expired — re-login
                response.success()
                self._login()

    # ── Job Submission ─────────────────────────────────────────────

    @tag("jobs")
    @task(10)
    def submit_job(self):
        """
        POST /jobs — submit a random AI model job.
        This is the most important endpoint to stress-test.
        Only draws from AVAILABLE_MODELS (models actually loaded locally).
        """
        model = random.choice(AVAILABLE_MODELS)
        payload = SAMPLE_INPUTS.get(model, SAMPLE_INPUTS["letter-gen"]).copy()
        payload["model"] = model

        with self.client.post(
            "/jobs",
            headers=self._auth_headers(),
            json=payload,
            name=f"/jobs [POST] ({model})",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                data = response.json()
                job_id = data.get("job_id")
                if job_id:
                    self.submitted_job_ids.append(job_id)
                    # Keep the list bounded so we don't leak memory
                    if len(self.submitted_job_ids) > 50:
                        self.submitted_job_ids = self.submitted_job_ids[-30:]
                response.success()
            elif response.status_code == 429:
                # Rate limited or concurrent job limit — expected under load
                response.success()
            elif response.status_code == 503:
                # Queue back-pressure — expected under heavy load
                response.success()
            else:
                response.failure(f"Job submit failed: {response.status_code} {response.text}")

    @tag("jobs")
    @task(8)
    def poll_job_status(self):
        """
        GET /jobs/{job_id} — poll a previously submitted job.
        Simulates the frontend polling loop.
        """
        if not self.submitted_job_ids:
            return

        job_id = random.choice(self.submitted_job_ids)
        with self.client.get(
            f"/jobs/{job_id}",
            headers=self._auth_headers(),
            name="/jobs/{job_id} [GET]",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 404):
                response.success()
            else:
                response.failure(f"Job poll failed: {response.status_code}")

    # ── Testing Endpoint (Public / No Auth) ────────────────────────

    @tag("testing")
    @task(2)
    def test_hf_live(self):
        """
        POST /test-hf-live — synchronous HF inference (public, no auth).
        Only draws from AVAILABLE_MODELS so results reflect real HF
        latency instead of "model not loaded" errors.
        """
        model = random.choice(AVAILABLE_MODELS)
        sample = SAMPLE_INPUTS[model]
        user_text = ""

        # Extract the user_text from the nested input dict
        if isinstance(sample.get("input"), dict):
            user_text = list(sample["input"].values())[0]
        else:
            user_text = str(sample.get("input", "கிளி"))

        with self.client.post(
            "/test-hf-live",
            json={"model": model, "user_text": user_text},
            name=f"/test-hf-live ({model})",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 503):
                # 503 = model unavailable (e.g. HF cold start / rate limit)
                response.success()
            else:
                response.failure(f"HF live test failed: {response.status_code}")

    # ── Metrics Endpoints ──────────────────────────────────────────
    # /metrics/raw and /metrics/summary are intentionally not exposed to
    # regular users (401 for any non-privileged token is correct behavior).
    # They're excluded from load testing since they don't represent real
    # user traffic. If you need to test them, do so with a dedicated
    # admin-token test rather than mixing it into this user simulation.

# ─────────────────────────────────────────────────────────────────────
# Custom Event Listeners (optional — for enhanced reporting)
# ─────────────────────────────────────────────────────────────────────
@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    logger.info("=" * 60)
    logger.info("  Tamil AI Backend — Locust Load Test Starting")
    logger.info(f"  Target host: {environment.host}")
    logger.info("=" * 60)


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    logger.info("=" * 60)
    logger.info("  Load Test Complete")
    logger.info("=" * 60)