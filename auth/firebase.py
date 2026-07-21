import jwt
import requests
import time
from threading import Lock
from fastapi import HTTPException, status
from settings.config import settings

# Thread-safe in-memory cache for Firebase public keys
_keys_cache = {}
_keys_expiry = 0
_keys_lock = Lock()

def get_firebase_public_keys():
    global _keys_cache, _keys_expiry
    now = time.time()
    
    # 1. Fast read path (cache hit and not expired)
    if _keys_cache and now < _keys_expiry:
        return _keys_cache

    # 2. Acquire lock to fetch
    with _keys_lock:
        # Double check inside lock
        if _keys_cache and now < _keys_expiry:
            return _keys_cache
            
        try:
            url = "https://www.googleapis.com/robot/v1/metadata/x509/securetoken-system@system.gserviceaccount.com"
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            
            # Read cache-control header max-age if present, default to 3600 seconds
            cache_control = response.headers.get("Cache-Control", "")
            max_age = 3600
            for part in cache_control.split(","):
                if "max-age" in part:
                    try:
                        max_age = int(part.split("=")[1].strip())
                    except Exception:
                        pass
                        
            _keys_cache = response.json()
            _keys_expiry = now + max_age
            return _keys_cache
        except Exception as e:
            # If fetch fails but we have a stale cache, fall back to it
            if _keys_cache:
                return _keys_cache
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Failed to fetch Firebase public keys: {e}"
            )

def verify_firebase_token(id_token: str) -> dict:
    """
    Decodes and cryptographically verifies a Firebase ID Token using Google's public certificates.
    Returns the decoded claims if valid. Raises HTTPException 401 otherwise.
    """
    project_id = settings.firebase_project_id
    if not project_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="FIREBASE_PROJECT_ID is not configured on the server."
        )

    try:
        # 1. Decode token header to get the key ID ('kid')
        unverified_header = jwt.get_unverified_header(id_token)
        kid = unverified_header.get("kid")
        if not kid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Firebase ID Token is missing 'kid' header."
            )

        # 2. Fetch public keys and find the matching certificate
        public_keys = get_firebase_public_keys()
        cert_pem = public_keys.get(kid)
        if not cert_pem:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Firebase ID Token 'kid' does not match any current public keys."
            )

        # 3. Decode and verify signature, audience, issuer
        # Note: PyJWT automatically converts the x509 PEM certificate string to a public key
        # when verifying RS256 token signatures.
        decoded = jwt.decode(
            id_token,
            cert_pem,
            algorithms=["RS256"],
            audience=project_id,
            issuer=f"https://securetoken.google.com/{project_id}"
        )
        
        # 4. Verify auth time is in the past
        auth_time = decoded.get("auth_time")
        if auth_time and auth_time > time.time():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Firebase ID Token auth_time is in the future."
            )
            
        return decoded

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Firebase ID Token has expired."
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid Firebase ID Token: {e}"
        )
