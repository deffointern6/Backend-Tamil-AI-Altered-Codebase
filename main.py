from fastapi import FastAPI
from services.registry import list_models
from api.jobs import router as jobs_router
from api.testing import router as testing_router

app = FastAPI()
app.include_router(jobs_router)
app.include_router(testing_router)

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