import re

# Pre-compile regex patterns at the module level for performance
LETTER_TYPE_PATTERN = re.compile(r'Letter type:</b>\s*(.*?)</p>', re.IGNORECASE)
CONFIDENCE_PATTERN = re.compile(r'Confidence:</b>\s*(.*?)</p>', re.IGNORECASE)
QUESTIONS_PATTERN = re.compile(r'<b>\d+\.\s*(.*?)</b>')


def _extract_text(html: str, pattern: re.Pattern) -> str | None:
    """Safely extracts text using a pre-compiled regex pattern."""
    if not isinstance(html, str):
        return None
    match = pattern.search(html)
    return match.group(1).strip() if match else None


def _extract_questions(html: str) -> list[str]:
    """Extracts bolded numbered questions from an HTML block."""
    if not isinstance(html, str):
        return []
    return [q.strip() for q in QUESTIONS_PATTERN.findall(html)]


def parse_letter_generator_output(raw) -> dict:
    """
    Safely cleans and parses the output from Hugging Face/Gradio for the letter-gen model.
    Handles tuple, list, and dict formats.
    """
    if isinstance(raw, (list, tuple)):
        data = list(raw)
    elif isinstance(raw, dict):
        data = raw.get("data", [])
        if isinstance(data, tuple):
            data = list(data)
    else:
        return {"error": "Invalid response format"}

    if not isinstance(data, list):
        return {"error": "Invalid data format"}

    if not data:
        return {"error": "Empty data array received from model"}

    return {
        "type": _extract_text(data[0], LETTER_TYPE_PATTERN) if len(data) > 0 else None,
        "confidence": _extract_text(data[0], CONFIDENCE_PATTERN) if len(data) > 0 else None,
        "questions": _extract_questions(data[1]) if len(data) > 1 else [],
        "current_question": data[3] if len(data) > 3 else None,
        "progress": data[5] if len(data) > 5 else None
    }


def parse_model_output(model_name: str, raw) -> dict | str | list | None:
    """
    Centralized dispatcher that cleans model output based on the model name.
    If parsing fails for a model that requires parsing, returns an error dict.
    """
    if model_name == "letter-gen":
        return parse_letter_generator_output(raw)

    # For other models, extract nested "data" if raw is an adapter result dictionary, or return raw directly
    if isinstance(raw, dict) and "data" in raw:
        return raw["data"]
    
    return raw
