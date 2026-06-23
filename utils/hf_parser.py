import re

# Pre-compile regex patterns at the module level for performance
LETTER_TYPE_PATTERN = re.compile(r'Letter type:</b>\s*(.*?)</p>', re.IGNORECASE)
EMAIL_TYPE_PATTERN = re.compile(r'Email type:</b>\s*(.*?)</p>', re.IGNORECASE)
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
    Handles multi-turn steps (start, next, prev, generate) and legacy formats.
    """
    if isinstance(raw, dict) and "step" in raw:
        step = raw["step"]
        session_id = raw.get("session_id")
        raw_data = raw.get("raw_data")

        if step == "start":
            if not isinstance(raw_data, (list, tuple)) or len(raw_data) < 7:
                return {"error": "Invalid raw data for start step"}
            return {
                "status": "success",
                "step": "ask_question",
                "session_id": session_id,
                "type": _extract_text(raw_data[0], LETTER_TYPE_PATTERN),
                "confidence": _extract_text(raw_data[0], CONFIDENCE_PATTERN),
                "questions": _extract_questions(raw_data[1]),
                "current_question": raw_data[3],
                "progress": raw_data[5],
                "answers_json": raw_data[2]
            }

        elif step == "next":
            if not isinstance(raw_data, (list, tuple)) or len(raw_data) < 5:
                return {"error": "Invalid raw data for next step"}
            return {
                "status": "success",
                "step": "ask_question",
                "session_id": session_id,
                "current_question": raw_data[0],
                "progress": raw_data[2],
                "answers_json": raw_data[3]
            }

        elif step == "prev":
            if not isinstance(raw_data, (list, tuple)) or len(raw_data) < 3:
                return {"error": "Invalid raw data for prev step"}
            return {
                "status": "success",
                "step": "ask_question",
                "session_id": session_id,
                "current_question": raw_data[0],
                "progress": raw_data[2]
            }

        elif step == "generate":
            return {
                "status": "done",
                "step": "generate",
                "letter": raw_data
            }

    # Fallback to legacy parsing if raw is just list/tuple/direct dict
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


def parse_email_generator_output(raw) -> dict:
    """
    Safely cleans and parses the output from Hugging Face/Gradio for the email-gen model.
    Handles multi-turn steps (start, next, prev, generate) and legacy formats.
    """
    if isinstance(raw, dict) and "step" in raw:
        step = raw["step"]
        session_id = raw.get("session_id")
        raw_data = raw.get("raw_data")

        if step == "start":
            if not isinstance(raw_data, (list, tuple)) or len(raw_data) < 7:
                return {"error": "Invalid raw data for start step"}
            
            email_type = _extract_text(raw_data[0], EMAIL_TYPE_PATTERN) or _extract_text(raw_data[0], LETTER_TYPE_PATTERN)
            if not email_type and len(raw_data) > 1:
                email_type = _extract_text(raw_data[1], EMAIL_TYPE_PATTERN) or _extract_text(raw_data[1], LETTER_TYPE_PATTERN)
                
            confidence = _extract_text(raw_data[0], CONFIDENCE_PATTERN)
            if not confidence and len(raw_data) > 1:
                confidence = _extract_text(raw_data[1], CONFIDENCE_PATTERN)

            return {
                "status": "success",
                "step": "ask_question",
                "session_id": session_id,
                "type": email_type,
                "confidence": confidence,
                "current_question": raw_data[3],
                "progress": raw_data[5],
                "answers_json": raw_data[2]
            }

        elif step == "next":
            if not isinstance(raw_data, (list, tuple)) or len(raw_data) < 5:
                return {"error": "Invalid raw data for next step"}
            return {
                "status": "success",
                "step": "ask_question",
                "session_id": session_id,
                "current_question": raw_data[0],
                "progress": raw_data[2],
                "answers_json": raw_data[3]
            }

        elif step == "prev":
            if not isinstance(raw_data, (list, tuple)) or len(raw_data) < 3:
                return {"error": "Invalid raw data for prev step"}
            return {
                "status": "success",
                "step": "ask_question",
                "session_id": session_id,
                "current_question": raw_data[0],
                "progress": raw_data[2]
            }

        elif step == "generate":
            return {
                "status": "done",
                "step": "generate",
                "email": raw_data
            }

    # Fallback to legacy parsing if raw is just list/tuple/direct dict
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

    email_type = _extract_text(data[0], EMAIL_TYPE_PATTERN) or _extract_text(data[0], LETTER_TYPE_PATTERN) if len(data) > 0 else None
    if not email_type and len(data) > 1:
        email_type = _extract_text(data[1], EMAIL_TYPE_PATTERN) or _extract_text(data[1], LETTER_TYPE_PATTERN)
        
    confidence = _extract_text(data[0], CONFIDENCE_PATTERN) if len(data) > 0 else None
    if not confidence and len(data) > 1:
        confidence = _extract_text(data[1], CONFIDENCE_PATTERN)

    return {
        "type": email_type,
        "confidence": confidence,
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
    elif model_name == "email-gen":
        return parse_email_generator_output(raw)

    # For other models, extract nested "data" if raw is an adapter result dictionary, or return raw directly
    if isinstance(raw, dict) and "data" in raw:
        return raw["data"]
    
    return raw
