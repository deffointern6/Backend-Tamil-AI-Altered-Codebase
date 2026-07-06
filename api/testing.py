from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, model_validator
from services.registry import get_model
from utils.hf_parser import parse_model_output
from typing import Any

router = APIRouter(prefix="/test-hf-live", tags=["Testing"])


def clean_whitespace(val: Any) -> Any:
    if isinstance(val, str):
        return val.strip()
    elif isinstance(val, dict):
        return {k: clean_whitespace(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [clean_whitespace(item) for item in val]
    return val


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
            if "user_text" in data:
                data["user_text"] = clean_whitespace(data["user_text"])
        return data

    @model_validator(mode="after")
    def check_char_limit(self) -> "TestRequest":
        from api.jobs import MODEL_CHAR_LIMITS
        limit = MODEL_CHAR_LIMITS.get(self.model, MODEL_CHAR_LIMITS["default"])
        
        if not self.user_text or not self.user_text.strip():
            raise ValueError("Input text cannot be empty.")
            
        if len(self.user_text) > limit:
            raise ValueError(f"Input text exceeds the maximum limit of {limit} characters for model '{self.model}'.")
        return self


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
