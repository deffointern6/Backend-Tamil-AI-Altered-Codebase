import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, model_validator
from services.registry import get_model
from utils.hf_parser import parse_model_output

from typing import Any

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/jobs", tags=["Jobs"])


# --- REQUEST MODELS ---
class JobRequest(BaseModel):
    model: str = "letter-gen"
    input: Any

    @model_validator(mode="before")
    @classmethod
    def validate_input(cls, data):
        if isinstance(data, dict):
            if "input" not in data and "user_text" in data:
                data["input"] = data["user_text"]
            if "model" not in data:
                data["model"] = "letter-gen"
        return data


# --- POST ROUTE ---
@router.post("")
def run_model(request: JobRequest):
    logger.info(f"[JOB START] Running model '{request.model}'")
    
    try:
        adapter = get_model(request.model)
    except Exception as e:
        logger.exception(f"Failed to load model '{request.model}' from registry")
        raise HTTPException(status_code=503, detail=f"Model initialization failed: {str(e)}")

    if not adapter:
        logger.warning(f"Model '{request.model}' requested but not found in registry")
        raise HTTPException(status_code=404, detail=f"Model '{request.model}' not found")

    try:
        raw = adapter.run(request.input)
    except Exception as e:
        logger.exception(f"Adapter run execution failed for model '{request.model}'")
        raise HTTPException(status_code=502, detail=f"Adapter run failed: {str(e)}")

    # Delegate output cleaning to the centralized dispatcher
    cleaned = parse_model_output(request.model, raw)

    # If parsing encountered a structural issue, send an appropriate validation error status
    if isinstance(cleaned, dict) and "error" in cleaned:
        logger.error(f"Response cleaning failed for model '{request.model}': {cleaned['error']}")
        raise HTTPException(status_code=422, detail=cleaned)

    logger.info(f"[JOB DONE] Successfully processed request for model '{request.model}'")
    return {
        "status": "done",
        "model": request.model,
        "result": cleaned
    }