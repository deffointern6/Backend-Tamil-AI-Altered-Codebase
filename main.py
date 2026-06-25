from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from services.registry import list_models
from api.jobs import router as jobs_router
from api.testing import router as testing_router
from api.metrics import router as metrics_router

app = FastAPI()

# Configure CORS so the frontend can interact with this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust this in production to match your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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