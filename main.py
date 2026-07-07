from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from services.registry import list_models
from api.jobs import router as jobs_router
from api.testing import router as testing_router
from api.metrics import router as metrics_router
from api.auth import router as auth_router
from middleware.auth_middleware import AuthMiddleware

from settings.config import settings

app = FastAPI(
    docs_url=None if settings.environment.lower() == "production" else "/docs",
    redoc_url=None if settings.environment.lower() == "production" else "/redoc",
    openapi_url=None if settings.environment.lower() == "production" else "/openapi.json"
)

@app.on_event("startup")
def startup_event():
    # Run watchdog to clean up stuck/orphaned jobs and recover lost queue items on boot
    from utils.watchdog import cleanup_stuck_jobs, recover_lost_queued_jobs
    try:
        cleanup_stuck_jobs(timeout_minutes=15)
        recover_lost_queued_jobs(timeout_minutes=10)
    except Exception as e:
        print(f"Startup watchdog cleanup/recovery failed: {e}")

# Configure CORS dynamically so the frontend can interact with this API
origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()] if settings.cors_origins else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuthMiddleware)
print("Allowed CORS origins:", origins)

app.include_router(auth_router)
app.include_router(jobs_router)
app.include_router(testing_router)
app.include_router(metrics_router)

@app.get("/")
def root():
    return {"status": "ok", "message": "API is working"}


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.get("/models", tags=["Metadata"])
def get_models():
    return {
        "status": "success",
        "models": list_models()
    }