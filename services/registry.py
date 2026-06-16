from threading import Lock
from settings.config import settings  
from services.adapters import HFAdapter, RunPodAdapter, HuggingFaceSpaceAdapter

# Thread Safety and Cache
_MODEL_CACHE = {}
_model_lock = Lock() 


LIVE_TEXT_SPACES = {
    "letter-gen": {
        "space": "DeffoTech/Letter_Generation",
        "api": "/detect_letter",
        "input": "user_request",
        "description": "Tamil Letter Generation"
    },
    "sentiment": {
        "space": "DeffoTech/Amil-Sentiment-Analyzer",
        "api": "/predict",
        "input": "text",
        "description": "Tamil Sentiment Analyzer"
    },
    "keyword": {
        "space": "DeffoTech/Tamil-Keyword-Extractor",
        "api": "/extract_keywords_ui",
        "input": "raw_input_text",
        "description": "Keyword Extraction"
    },
    "paraphrase-gen": {
        "space": "DeffoTech/Tamil-Paraphrase-AI",
        "api": "/generate_paraphrase",
        "input": "text",
        "description": "Paraphrasing"
    },
    "mcq-gen": {
        "space": "DeffoTech/quiz_generation",
        "api": "/process_text",
        "input": "text",
        "description": "MCQ Generator"
    },
    "dialogue-gen": {
        "space": "DeffoTech/tamil_dialogue_generation",
        "api": "/safe_generate_dialogue",
        "input": "scene_context",
        "description": "Dialogue Generator"
    },
    "offensive-detector": {
        "space": "DeffoTech/Tamil-Offensive-Detector-Final",
        "api": "/moderate",
        "input": "text",
        "description": "Offensive Content Detection"
    },
    "tongue-twister": {
        "space": "DeffoTech/Tamil-toungue-twister",
        "api": "/predict",
        "input": "text",
        "description": "Tongue Twister Generator"
    },
    "poem-gen": {
        "space": "DeffoTech/Tamil-Poem-Generator-V6",
        "api": "/generate_poem_ui",
        "input": "topic",
        "description": "Poem Generator"
    },
    "email-gen": {
        "space": "DeffoTech/Tamil_Email_Generation",
        "api": "/lambda",
        "input": "text",
        "description": "Email Generator"
    }
}

LEGACY_MODELS = {
    "ocr": {
        "type": "file",
        "description": "Tamil OCR",
        "builder": lambda: HFAdapter(settings.ocr_endpoint, settings.hf_token)
    },
    "voice-clone": {
        "type": "audio",
        "description": "Voice Cloning",
        "builder": lambda: RunPodAdapter(settings.voice_endpoint_id, settings.runpod_key)
    }
}

def get_model(model_name: str):
    with _model_lock:
        if model_name in _MODEL_CACHE:
            return _MODEL_CACHE[model_name]

        # HuggingFace Spaces
        if model_name in LIVE_TEXT_SPACES:
            config = LIVE_TEXT_SPACES[model_name]

            adapter = HuggingFaceSpaceAdapter(
                config["space"],
                config["api"],
                settings.hf_token,
                config["input"]
            )

            _MODEL_CACHE[model_name] = adapter
            return adapter

        # Legacy Models
        if model_name in LEGACY_MODELS:
            adapter = LEGACY_MODELS[model_name]["builder"]()
            _MODEL_CACHE[model_name] = adapter
            return adapter

        return None

def list_models():
    models = []

    # HuggingFace Spaces
    for name, config in LIVE_TEXT_SPACES.items():
        models.append({
            "name": name,
            "type": "text",
            "source": "hf-space",
            "description": config["description"]
        })

    # Legacy
    for name, config in LEGACY_MODELS.items():
        models.append({
            "name": name,
            "type": config["type"],
            "source": "custom",
            "description": config["description"]
        })

    return models