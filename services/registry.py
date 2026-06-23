from threading import Lock
from settings.config import settings  
from services.adapters import HuggingFaceSpaceAdapter, LetterGenAdapter, EmailGenAdapter, ProofreaderAdapter

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
        "space": "DeffoTech/Tamil_MCQ_Quiz",
        "api": "/process_text",
        "input": "text",
        "description": "MCQ Generator"
    },
    "offensive-detector": {
        "space": "DeffoTech/Tamil-Offensive-Detector-Final",
        "api": "/moderate",
        "input": "text",
        "description": "Offensive Content Detection"
    },
    "tongue-twister": {
        "space": "DeffoTech/Tamil-Tongue-Twister_final",
        "api": "/generate_twister_ui",
        "input": "user_input",
        "description": "Tongue Twister Generator"
    },
    "poem-gen": {
        "space": "DeffoTech/Tamil-Poem-Generator-V6",
        "api": "/generate_poem_ui",
        "input": "topic",
        "description": "Poem Generator"
    },
    "email-gen": {
        "space": "DeffoTech/Letter_Generation",
        "api": "/lambda",
        "input": "text",
        "description": "Email Generator"
    },
    "proofreader": {
        "space": "hxari/tamil-spell-checker",
        "api": "/check",
        "input": "word",
        "description": "Tamil Proofreader"
    }
}


def get_model(model_name: str):
    # 1. Fast read path (no lock needed for reading in Python)
    if model_name in _MODEL_CACHE:
        return _MODEL_CACHE[model_name]

    # 2. Build the adapter outside the lock to avoid blocking other threads
    adapter = None
    if model_name in LIVE_TEXT_SPACES:
        config = LIVE_TEXT_SPACES[model_name]
        if model_name == "letter-gen":
            adapter = LetterGenAdapter(config["space"], settings.hf_token)
        elif model_name == "email-gen":
            adapter = EmailGenAdapter(config["space"], settings.hf_token)
        elif model_name == "proofreader":
            adapter = ProofreaderAdapter(config["space"], settings.hf_token)
        else:
            adapter = HuggingFaceSpaceAdapter(
                config["space"], config["api"], settings.hf_token, config["input"]
            )


    # 3. Lock only to safely write it to the cache
    if adapter:
        with _model_lock:
            # Double-check in case another thread wrote it while we were building
            if model_name not in _MODEL_CACHE:
                _MODEL_CACHE[model_name] = adapter
            return _MODEL_CACHE[model_name]

    return None

# def get_model(model_name: str):
#     with _model_lock:
#         if model_name in _MODEL_CACHE:
#             return _MODEL_CACHE[model_name]

#         # HuggingFace Spaces
#         if model_name in LIVE_TEXT_SPACES:
#             config = LIVE_TEXT_SPACES[model_name]

#             adapter = HuggingFaceSpaceAdapter(
#                 config["space"],
#                 config["api"],
#                 settings.hf_token,
#                 config["input"]
#             )

#             _MODEL_CACHE[model_name] = adapter
#             return adapter

#         return None

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



    return models