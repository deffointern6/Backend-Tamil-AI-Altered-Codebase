# Tamil AI Backend

A robust, scalable backend designed to orchestrate and serve various Tamil NLP models hosted on Hugging Face/Gradio Spaces. It uses background task queueing (Redis Queue) to handle long-running model inferences asynchronously, stores task records, and includes a lightweight, database-free metrics system designed for deployment health checks.

---

## Architecture Overview

The system consists of the following major components:

1. **FastAPI Web Server**: Exposes REST endpoints for submitting asynchronous job requests, polling job status, calling models synchronously (for testing), retrieving model metadata, and querying service metrics.
2. **Redis Queue**: Offloads model executions from the API thread pool to asynchronous worker processes, ensuring high API responsiveness.
3. **Background Worker**: Listens to the Redis queue, pulls tasks, runs model inference, parses responses, saves output, and logs telemetry details.
4. **Model Adapter Layer**: Implements a unified adapter pattern to abstract interaction logic with Gradio Clients and raw HTTP space APIs.
5. **Database Layer**: Tracks job history, statuses (`queued`, `running`, `done`, `error`), and outputs in PostgreSQL/SQLite using SQLAlchemy.
6. **Telemetry & Metrics Engine**: A lightweight, database-free telemetry logger that records performance metrics to a local log file and calculates real-time sliding window aggregates.

```mermaid
flowchart TD
    Client -->|1. Submit Job POST /jobs| FastAPI[FastAPI Web Server]
    FastAPI -->|2. Create Record| DB[(SQL Database)]
    FastAPI -->|3. Enqueue job_id| Redis[(Redis Queue)]
    
    Worker[Background Worker] -->|4. Pull Job| Redis
    Worker -->|5. Update Status: running| DB
    Worker -->|6. Query Space Status| HF_API[Hugging Face API]
    Worker -->|7. Call Adapter| Gradio[Gradio / HF Space]
    
    Worker -->|8. Record Metrics| Metrics[(Local Metric Logs)]
    Worker -->|9. Update Job Outcome| DB
    
    DeployTools[Deployment CLI / CI] -->|Check Metrics| FastAPI
    DeployTools -->|Run Script| CLI[CLI Metrics Checker]
    CLI -->|Parse logs| Metrics
```

---

## Key Components & Logic

### 1. Model Adapters
Wraps communication with Hugging Face Space endpoints. It defines a base model connector interface and concrete implementations:
- Standard Gradio-based model connector.
- Conversational adapters supporting multi-turn parameters (actions like `start`, `next`, `prev`, `generate`) with session hashes.
- Microservice adapters interacting directly with spellchecker microservices over HTTP GET.

### 2. Registry
A thread-safe registry mapping model identifiers to Space configurations. Employs a thread lock to cache adapter client instantiations safely across execution threads.

### 3. Output Parsers
Cleans and parses raw HTML/markdown payloads returned by the models (extracting letter type, confidence score, progress indicators, questions, etc.) using regular expressions.

### 4. Telemetry & Metrics
Logs job telemetry to a local file and computes statistics across four sliding windows:
- **Last 1 Minute**: For current request rates.
- **Last 5 Minutes**: Ideal for verifying deployment health.
- **Last 1 Hour**: Captures short-term patterns.
- **Last 24 Hours**: Tracks daily throughput.

It calculates:
- Requests count & P95 latency (per model).
- Failed requests (total & per model).
- Space wake-up delay frequencies and duration.
- Live queue depth in Redis.

---

## API Reference

### Models Metadata
* **`GET /models`**
  Returns a list of all active model names, types, sources, and descriptions.

### Asynchronous Jobs
* **`POST /jobs`**
  Submits a job to the background queue.
  * Request Body:
    ```json
    {
      "model": "letter-gen",
      "input": "Write a leaves letter to my principal"
    }
    ```
  * Response:
    ```json
    {
      "job_id": "abc-123-uuid",
      "status": "queued"
    }
    ```
* **`GET /jobs/{job_id}`**
  Retrieves status (`queued`, `running`, `done`, `error`), result payload, or errors of the job.

### Live Testing
* **`POST /test-hf-live`**
  Runs model adapters synchronously. Useful for sanity checks without database records or Redis queues.

### Telemetry & Metrics
* **`GET /metrics/summary`**
  Returns windowed aggregate statistics (Total requests, P95 latency, failure rates, wake-up delays).
* **`GET /metrics/raw`**
  Returns the latest raw entries logged. Supports parameter `limit` (default: 100, max: 1000).

---

## Configuration & Setup

### Environment Variables
Configure the application using a local environment file:
```ini
# Hugging Face Access Token
HF_TOKEN = hf_yourtokenhere
# Database URL (SQLAlchemy compatible)
DATABASE_URL = postgresql://user:password@localhost:5432/db
# Redis connection URL (used for RQ)
REDIS_URL = redis://localhost:6379/0
```

### Running the API
Start the FastAPI server:
```bash
uvicorn main:app --reload --port 8000
```

### Running the Worker
Start the background worker:
```bash
rq worker default
```

### Running Tests
Execute unit tests using unittest:
```bash
python -m unittest discover tests
```

---

## Deployment Health Verification

To check the health of the system during or after a deployment:

### 1. Check Metrics via CLI
Run the helper script:
```bash
python check_metrics.py
```
This prints the queue depth, error rates, and latency averages across all sliding windows.

### 2. Check Metrics via HTTP
Curl the summary endpoint to inspect health parameters automatically:
```bash
curl http://localhost:8000/metrics/summary
```