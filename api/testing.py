from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, model_validator
from services.registry import get_model
from utils.hf_parser import parse_model_output

router = APIRouter(prefix="/test-hf-live", tags=["Testing"])


class TestRequest(BaseModel):
    model: str = "letter-gen"
    user_text: str

    @model_validator(mode="before")
    @classmethod
    def validate_input(cls, data):
        if isinstance(data, dict):
            if "user_text" not in data and "input" in data:
                data["user_text"] = data["input"]
            if "user_text" not in data:
                data["user_text"] = "Write a school leave letter in Tamil"
            if "model" not in data:
                data["model"] = "letter-gen"
        return data


@router.post("")
def test_huggingface_live_call(request: TestRequest):
    try:
        adapter = get_model(request.model)
    except Exception as e:
        raise HTTPException(
            status_code=503, 
            detail=f"Model initialization failed: {str(e)}"
        )

    if not adapter:
        raise HTTPException(
            status_code=404, 
            detail=f"Model adapter for '{request.model}' not found."
        )

    try:
        raw = adapter.run(request.user_text)
        
        # Delegate parsing to unified parser dispatcher
        cleaned = parse_model_output(request.model, raw)
        
        if isinstance(cleaned, dict) and "error" in cleaned:
            raise HTTPException(status_code=422, detail=cleaned)

        return {
            "status": "success",
            "result": cleaned
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"HF call failed: {str(e)}")
