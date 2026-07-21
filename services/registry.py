from threading import Lock
from settings.config import settings  
from services.adapters import (
    HuggingFaceSpaceAdapter,
    LetterGenAdapter,
    EmailGenAdapter,
    ProofreaderAdapter,
    RunPodAdapter,
    FallbackAdapter,
    MCQGenAdapter,
)

# Thread Safety and Cache
_MODEL_CACHE = {}
_model_lock = Lock() 

MODEL_CHAR_LIMITS = {
    "letter-gen": 1000,
    "email-gen": 1000,
    "poem-gen": 500,
    "tongue-twister": 200,
    "paraphrase-gen": 5000,
    "mcq-gen": 3000,
    "proofreader": 5000,
    "default": 1000
}


LIVE_TEXT_SPACES = {
    "letter-gen": {
        "space": "DeffoTech/Letter_Generation",
        "api": "/detect_letter",
        "input": "user_request",
        "description": "Tamil Letter Generation"
    },
    "paraphrase-gen": {
        "space": "DeffoTech/Tamil-Paraphrase-AI",
        "api": "/generate_paraphrase",
        "input": "text",
        "description": "Paraphrasing"
    },
    "mcq-gen": {
        "space": "DeffoTech/MCQ_generator",
        "api": "/on_generate",
        "input": "passage",
        "description": "MCQ Generator"
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
        "space": "DeffoTech/Tamil_Email_Generation",
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


# ──────────────────────────────────────────────────────────────────────
# RunPod Serverless Endpoints (fallback when HF Spaces are down)
# ──────────────────────────────────────────────────────────────────────
# Uncomment and fill in the endpoint IDs once you deploy to RunPod.
# Any model listed here will automatically get a FallbackAdapter that
# tries HF first and falls over to RunPod only if HF completely fails.
#
# Format:  "model-name": "runpod-endpoint-id"
#
# RUNPOD_ENDPOINTS = {
#     "letter-gen":      "your-letter-gen-endpoint-id",
#     "paraphrase-gen":  "your-paraphrase-gen-endpoint-id",
#     "mcq-gen":         "your-mcq-gen-endpoint-id",
#     "tongue-twister":  "your-tongue-twister-endpoint-id",
#     "poem-gen":        "your-poem-gen-endpoint-id",
#     "email-gen":       "your-email-gen-endpoint-id",
#     "proofreader":     "your-proofreader-endpoint-id",
# }
RUNPOD_ENDPOINTS: dict[str, str] = {}


def _build_runpod_adapter(model_name: str) -> RunPodAdapter | None:
    """
    Build a RunPodAdapter for the given model if a RunPod endpoint is
    configured AND the API key is present. Returns None otherwise.
    """
    endpoint_id = RUNPOD_ENDPOINTS.get(model_name)
    if not endpoint_id or not settings.runpod_api_key:
        return None

    return RunPodAdapter(
        endpoint_id=endpoint_id,
        api_key=settings.runpod_api_key,
        model_name=model_name,
    )


def _maybe_wrap_with_fallback(model_name: str, primary: "ModelAdapter") -> "ModelAdapter":
    """
    If a RunPod fallback endpoint is configured for this model,
    wrap the primary adapter in a FallbackAdapter. Otherwise
    return the primary adapter as-is.
    """
    runpod = _build_runpod_adapter(model_name)
    if runpod is None:
        return primary
    return FallbackAdapter(primary=primary, fallback=runpod, model_name=model_name)


def get_model(model_name: str):
    # 1. Fast read path (no lock needed for reading in Python)
    if model_name in _MODEL_CACHE:
        return _MODEL_CACHE[model_name]

    # 2. Build the adapter outside the lock to avoid blocking other threads
    adapter = None
    if model_name in LIVE_TEXT_SPACES:
        config = LIVE_TEXT_SPACES[model_name]
        
        # Resolve target host (Local URL or remote HF Space)
        if getattr(settings, "use_local_models", False):
            port = settings.local_model_ports.get(model_name)
            target_source = f"http://127.0.0.1:{port}"
        else:
            target_source = config["space"]

        if model_name == "letter-gen":
            adapter = LetterGenAdapter(target_source, settings.hf_token)
        elif model_name == "email-gen":
            adapter = EmailGenAdapter(target_source, settings.hf_token)
        elif model_name == "proofreader":
            adapter = ProofreaderAdapter(target_source, settings.hf_token)
        elif model_name == "mcq-gen":
            adapter = MCQGenAdapter(target_source, settings.hf_token)
        else:
            adapter = HuggingFaceSpaceAdapter(
                target_source, config["api"], settings.hf_token, config["input"]
            )

        # Wrap with RunPod fallback if endpoint is configured
        if adapter:
            adapter = _maybe_wrap_with_fallback(model_name, adapter)

    # 3. Lock only to safely write it to the cache
    if adapter:
        with _model_lock:
            # Double-check in case another thread wrote it while we were building
            if model_name not in _MODEL_CACHE:
                _MODEL_CACHE[model_name] = adapter
            return _MODEL_CACHE[model_name]

    return None


def list_models():
    models = []

    # HuggingFace Spaces
    for name, config in LIVE_TEXT_SPACES.items():
        has_fallback = name in RUNPOD_ENDPOINTS and bool(settings.runpod_api_key)
        limit = MODEL_CHAR_LIMITS.get(name, MODEL_CHAR_LIMITS["default"])
        models.append({
            "name": name,
            "type": "text",
            "source": "hf-space",
            "fallback": "runpod" if has_fallback else None,
            "description": config["description"],
            "character_limit": limit
        })

    return models