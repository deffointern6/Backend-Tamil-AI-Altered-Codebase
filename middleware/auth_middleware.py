from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from auth.jwt import decode_access_token
from database.db import SessionLocal
from database.models_db import User

# Routes that do NOT require authentication
PUBLIC_PREFIXES = [
    "/auth",
    "/health",
    "/models",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/test-hf-live",
]

class AuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware to authenticate incoming requests via JWT tokens.
    Extracts the token, validates it, and attaches the User object to request.state.user.
    Also protects defined prefixes from unauthorized access.
    """
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.user = None

        # 1. Always allow CORS preflight (OPTIONS) requests through
        #    The browser sends these without auth headers before every cross-origin request.
        if request.method == "OPTIONS":
            response = await call_next(request)
            return response

        # 2. Skip auth for public routes and the root path
        path = request.url.path
        if path == "/" or any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
            response = await call_next(request)
            return response

        # 3. Parse Authorization Header
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            payload = decode_access_token(token)
            if payload:
                username = payload.get("sub")
                if username:
                    # Query user using a manual db session since this runs outside dependency injection context
                    db = SessionLocal()
                    try:
                        user = db.query(User).filter(User.username == username).first()
                        if user and user.is_active:
                            request.state.user = user
                    except Exception:
                        pass
                    finally:
                        db.close()

        # 4. Enforce Authentication for Protected Routes (everything not public)
        if not request.state.user:
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication credentials were not provided or are invalid."}
            )

        response = await call_next(request)
        return response

