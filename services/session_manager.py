import time
import uuid
import logging
from threading import Lock
from typing import Dict, Any
from gradio_client import Client as GradioClient

logger = logging.getLogger(__name__)

class Session:
    def __init__(self, client: GradioClient):
        self.client = client
        self.created_at = time.time()
        self.last_accessed = time.time()

class SessionManager:
    def __init__(self, ttl_seconds: int = 1800):
        self._sessions: Dict[str, Session] = {}
        self._lock = Lock()
        self.ttl_seconds = ttl_seconds

    def create_session(self, space_id: str, token: str) -> str:
        """Instantiates a new Gradio Client and stores it in the session cache."""
        session_id = str(uuid.uuid4())
        try:
            logger.info(f"[SESSION_MANAGER] Creating new GradioClient session for {space_id}")
            client = GradioClient(space_id, token=token)
            session = Session(client)
            
            with self._lock:
                # Run self-cleanup on session creation to prevent memory build-up
                self._cleanup_expired_unlocked()
                self._sessions[session_id] = session
                
            logger.info(f"[SESSION_MANAGER] Session {session_id} created successfully.")
            return session_id
        except Exception as e:
            logger.exception(f"Failed to create GradioClient session for space {space_id}")
            raise RuntimeError(f"Session initialization failed: {str(e)}")

    def get_client(self, session_id: str) -> GradioClient | None:
        """Retrieves a Gradio Client by session_id and updates its last accessed timestamp."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                # Check if expired
                if time.time() - session.last_accessed > self.ttl_seconds:
                    logger.warning(f"[SESSION_MANAGER] Session {session_id} accessed but has expired. Removing.")
                    self._sessions.pop(session_id, None)
                    return None
                
                session.last_accessed = time.time()
                return session.client
            return None

    def delete_session(self, session_id: str) -> bool:
        """Explicitly deletes a session client from the cache."""
        with self._lock:
            if session_id in self._sessions:
                self._sessions.pop(session_id, None)
                logger.info(f"[SESSION_MANAGER] Explicitly deleted session {session_id}.")
                return True
            return False

    def _cleanup_expired_unlocked(self):
        """Cleans up expired sessions. Must be called while holding self._lock."""
        now = time.time()
        expired_ids = [
            sid for sid, sess in self._sessions.items()
            if now - sess.last_accessed > self.ttl_seconds
        ]
        for sid in expired_ids:
            self._sessions.pop(sid, None)
            logger.info(f"[SESSION_MANAGER] Garbage collected expired session {sid}.")

# Shared singleton instance
session_manager = SessionManager()
