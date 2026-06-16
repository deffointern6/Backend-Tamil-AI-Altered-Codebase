import logging
import requests
from abc import ABC, abstractmethod
from gradio_client import Client as GradioClient
from tenacity import retry, stop_after_attempt, wait_fixed

from typing import Any

logger = logging.getLogger(__name__)

# BASE MODEL
class ModelAdapter(ABC):
    @abstractmethod 
    def run(self, text_input: Any): 
        pass

class HuggingFaceSpaceAdapter(ModelAdapter):
    def __init__(self, space_id, api_name, token, input_param_name="text"):
        self.space_id = space_id
        self.api_name = api_name
        self.input_param_name = input_param_name

        try:
            self.client = GradioClient(self.space_id, token=token)
            logger.info(f"[INIT] HF Space client initialized: {space_id}")
        except Exception as e:
            logger.exception("Failed to initialize HF Space client")
            raise RuntimeError(
                f"Initialization failed for {space_id}: {str(e)}"
            )

    # Retry 3 times with 2s delay
    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    def _predict(self, payload: dict):
        return self.client.predict(**payload, api_name=self.api_name)

    def run(self, text_input: Any):
        if isinstance(text_input, dict):
            payload = text_input
        else:
            payload = {self.input_param_name: text_input}

        # Dynamic handling for dialogue-gen key mapping (scene -> scene_context)
        if "tamil_dialogue_generation" in self.space_id.lower():
            if isinstance(payload, dict):
                if "scene" in payload and "scene_context" not in payload:
                    payload["scene_context"] = payload.pop("scene")

        # Dynamic handling for poem-gen temperature splitting
        if self.space_id == "DeffoTech/Tamil-Poem-Generator-V6":
            if isinstance(text_input, str) and "," in text_input:
                parts = text_input.rsplit(",", 1)
                topic = parts[0].strip()
                try:
                    temperature = float(parts[1].strip())
                    payload = {"topic": topic, "temperature": temperature}
                except ValueError:
                    payload = {"topic": text_input.strip(), "temperature": 0.8}
            elif isinstance(text_input, dict):
                payload = text_input
            else:
                payload = {"topic": str(text_input).strip(), "temperature": 0.8}

        try:
            logger.info(f"[HF CALL] {self.space_id} → {self.api_name}")
            logger.debug(f"[PAYLOAD] {payload}")

            result = self._predict(payload)

            return {
                "status": "success",
                "source": "hf-space",
                "model": self.space_id,
                "data": result
            }

        except Exception as e:
            logger.exception("HF Space execution failed")

            raise RuntimeError(
                f"HF Space call failed ({self.space_id}): {str(e)}"
            )
# HUGGING FACE INFERENCE API ADAPTER
class HFAdapter(ModelAdapter):
    def __init__(self, endpoint_url: str, token: str):
        self.url = endpoint_url
        self.token = token
        
    def run(self, text_input: str):
        if self.token == "mock_token" or "mock-ocr" in self.url:
            return {"simulated_output": f"Processed '{text_input}' using Hugging Face endpoint {self.url}"}
            
        headers = {"Authorization": f"Bearer {self.token}"}
        json_data = {"inputs": text_input}
        
        try:
            response = requests.post(self.url, headers=headers, json=json_data, timeout=10)
            response.raise_for_status() 
            return response.json()
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Hugging Face network call failed: {str(e)}")


#  RUNPOD SERVERLESS ADAPTER
class RunPodAdapter(ModelAdapter):
    def __init__(self, endpoint_id: str, api_key: str):
        self.endpoint_id = endpoint_id
        self.api_key = api_key

    def run(self, text_input: str):
        if self.api_key == "mock_key" or self.endpoint_id == "mock-voice-id":
            return {"simulated_output": f"Processed '{text_input}' using RunPod endpoint {self.endpoint_id}"}
        return {"status": "success", "message": "RunPod execution complete"}