import logging
import requests
from abc import ABC, abstractmethod
from gradio_client import Client as GradioClient
from tenacity import retry, stop_after_attempt, wait_fixed

import sys
from pathlib import Path
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


class LetterGenAdapter(ModelAdapter):
    def __init__(self, space_id: str, token: str):
        self.space_id = space_id
        self.token = token
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = GradioClient(self.space_id, token=self.token)
        return self._client

    def run(self, text_input: Any):
        is_start = False
        prompt = ""
        
        if isinstance(text_input, str):
            is_start = True
            prompt = text_input
        elif isinstance(text_input, dict):
            if "session_id" not in text_input:
                is_start = True
                prompt = text_input.get("prompt", text_input.get("user_text", text_input.get("input", "")))
        else:
            raise ValueError("Invalid request format for letter-gen model.")

        client = self.client

        if is_start:
            try:
                session_id = client.session_hash
                logger.info(f"[LetterGenAdapter] Created session {session_id} for {self.space_id}")
                
                logger.info(f"[LetterGenAdapter] Calling /detect_letter for session {session_id}")
                res = client.predict(prompt, api_name="/detect_letter")
                return {
                    "status": "success",
                    "step": "start",
                    "session_id": session_id,
                    "raw_data": res
                }
            except Exception as e:
                raise RuntimeError(f"Gradio Space detect_letter failed: {str(e)}")

        session_id = text_input.get("session_id")
        if not session_id:
            raise ValueError("session_id is required for multi-turn requests.")

        client.session_hash = session_id

        action = text_input.get("action", "next")

        if action == "next":
            answer = text_input.get("answer", "")
            try:
                logger.info(f"[LetterGenAdapter] Calling /next_question for session {session_id}")
                res = client.predict(answer, api_name="/next_question")
                return {
                    "status": "success",
                    "step": "next",
                    "session_id": session_id,
                    "raw_data": res
                }
            except Exception as e:
                raise RuntimeError(f"Gradio Space next_question failed: {str(e)}")

        elif action == "prev":
            try:
                logger.info(f"[LetterGenAdapter] Calling /prev_question for session {session_id}")
                res = client.predict(api_name="/prev_question")
                return {
                    "status": "success",
                    "step": "prev",
                    "session_id": session_id,
                    "raw_data": res
                }
            except Exception as e:
                raise RuntimeError(f"Gradio Space prev_question failed: {str(e)}")

        elif action == "generate":
            user_request = text_input.get("user_request", "")
            answers_json = text_input.get("answers_json", "{}")
            template_index = float(text_input.get("template_index", 0))
            
            try:
                logger.info(f"[LetterGenAdapter] Calling /generate_letter for session {session_id}")
                res = client.predict(user_request, answers_json, template_index, api_name="/generate_letter")
                return {
                    "status": "success",
                    "step": "generate",
                    "raw_data": res
                }
            except Exception as e:
                raise RuntimeError(f"Gradio Space generate_letter failed: {str(e)}")

        else:
            raise ValueError(f"Unknown action '{action}' for letter-gen model.")


class EmailGenAdapter(ModelAdapter):
    def __init__(self, space_id: str, token: str):
        self.space_id = space_id
        self.token = token
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = GradioClient(self.space_id, token=self.token)
        return self._client

    def run(self, text_input: Any):
        is_start = False
        prompt = ""
        
        if isinstance(text_input, str):
            is_start = True
            prompt = text_input
        elif isinstance(text_input, dict):
            if "session_id" not in text_input:
                is_start = True
                prompt = text_input.get("prompt", text_input.get("user_text", text_input.get("input", text_input.get("user_request", ""))))
        else:
            raise ValueError("Invalid request format for email-gen model.")

        client = self.client

        if is_start:
            try:
                session_id = client.session_hash
                logger.info(f"[EmailGenAdapter] Created session {session_id} for {self.space_id}")
                
                logger.info(f"[EmailGenAdapter] Calling /detect_email for session {session_id}")
                res = client.predict(prompt, api_name="/detect_email")
                return {
                    "status": "success",
                    "step": "start",
                    "session_id": session_id,
                    "raw_data": res
                }
            except Exception as e:
                raise RuntimeError(f"Gradio Space detect_email failed: {str(e)}")

        session_id = text_input.get("session_id")
        if not session_id:
            raise ValueError("session_id is required for multi-turn requests.")

        client.session_hash = session_id

        action = text_input.get("action", "next")

        if action == "next":
            answer = text_input.get("answer", "")
            try:
                logger.info(f"[EmailGenAdapter] Calling /next_question for session {session_id}")
                res = client.predict(answer, api_name="/next_question")
                return {
                    "status": "success",
                    "step": "next",
                    "session_id": session_id,
                    "raw_data": res
                }
            except Exception as e:
                raise RuntimeError(f"Gradio Space next_question failed: {str(e)}")

        elif action == "prev":
            try:
                logger.info(f"[EmailGenAdapter] Calling /prev_question for session {session_id}")
                res = client.predict(api_name="/prev_question")
                return {
                    "status": "success",
                    "step": "prev",
                    "session_id": session_id,
                    "raw_data": res
                }
            except Exception as e:
                raise RuntimeError(f"Gradio Space prev_question failed: {str(e)}")

        elif action == "generate":
            answers_json = text_input.get("answers_json", "{}")
            
            try:
                logger.info(f"[EmailGenAdapter] Calling /generate_email for session {session_id}")
                res = client.predict(answers_json, api_name="/generate_email")
                return {
                    "status": "success",
                    "step": "generate",
                    "raw_data": res
                }
            except Exception as e:
                raise RuntimeError(f"Gradio Space generate_email failed: {str(e)}")

        else:
            raise ValueError(f"Unknown action '{action}' for email-gen model.")


class ProofreaderAdapter(ModelAdapter):
    def __init__(self, space_id: str = "hxari/tamil-spell-checker", token: str = None):
        self.space_id = space_id
        self.token = token
        
        # Subdomain of hxari/tamil-spell-checker is hxari-tamil-spell-checker
        subdomain = self.space_id.replace("/", "-").lower()
        self.api_url = f"https://{subdomain}.hf.space/check"
        logger.info(f"[INIT] ProofreaderAdapter initialized for remote Space: {self.api_url}")

    def run(self, text_input: Any):
        word = ""
        if isinstance(text_input, str):
            word = text_input
        elif isinstance(text_input, dict):
            word = text_input.get("word", text_input.get("input", text_input.get("text", "")))
        else:
            raise ValueError("Invalid request format for proofreader model.")

        if not word:
            raise ValueError("Input text cannot be empty.")

        try:
            logger.info(f"[PROOFREADER CALL] {self.space_id} → GET {self.api_url}")
            headers = {}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"

            response = requests.get(
                self.api_url,
                params={"word": word},
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            result = response.json()

            return {
                "status": "success",
                "source": "hf-space",
                "model": self.space_id,
                "data": result
            }
        except Exception as e:
            logger.exception("Remote proofreader space call failed")
            raise RuntimeError(f"Remote proofreader space call failed ({self.space_id}): {str(e)}")