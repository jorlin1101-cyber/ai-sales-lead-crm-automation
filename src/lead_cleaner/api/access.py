"""Single-workspace operator access and isolated, offline-only public demo sessions."""

import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from urllib.parse import urlsplit

from fastapi import Request
from starlette.responses import JSONResponse

from lead_cleaner.config import Settings


def install_access(api) -> None:
    ephemeral_secret = secrets.token_bytes(32)
    quotas: defaultdict[str, deque[float]] = defaultdict(deque)

    @api.middleware("http")
    async def enforce_access(request: Request, call_next):
        settings: Settings = request.app.state.settings
        path = request.url.path
        if path == "/webhooks/inbound":
            # Endpoint verifies a timestamped HMAC before it processes any payload.
            request.state.principal, request.state.role = "operator", "operator"
            return await call_next(request)
        public_path = path in {"/", "/health"} or path.startswith("/assets/")
        try:
            content_length = int(request.headers.get("content-length", "0"))
        except ValueError:
            return JSONResponse({"detail": "Invalid content length"}, status_code=400)
        if content_length < 0:
            return JSONResponse({"detail": "Invalid content length"}, status_code=400)
        if content_length > 65536:
            return JSONResponse({"detail": "Request too large"}, status_code=413)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if request.headers.get("sec-fetch-site") == "cross-site" or (
                origin and urlsplit(origin).netloc != request.url.netloc
            ):
                return JSONResponse(
                    {"detail": "Cross-site writes are not allowed."}, status_code=403
                )
        token = settings.service_access_token
        supplied = request.headers.get("authorization", "").removeprefix("Bearer ")
        authorized = token is not None and hmac.compare_digest(supplied, token.get_secret_value())
        local = (
            settings.service_access_mode == "local"
            and request.client
            and request.client.host in {"127.0.0.1", "::1", "testclient"}
        )
        if authorized or local:
            request.state.principal = "operator"
            request.state.role = "operator"
            return await call_next(request)
        if settings.service_access_mode != "public_demo":
            if not public_path:
                return JSONResponse({"detail": "Operator access token required."}, status_code=401)
            request.state.principal, request.state.role = "anonymous", "guest"
            return await call_next(request)
        secret = (
            settings.service_session_secret.get_secret_value().encode()
            if settings.service_session_secret
            else ephemeral_secret
        )
        raw_cookie = request.cookies.get("leadflow_demo", "")
        pieces = raw_cookie.split(".")
        valid = (
            len(pieces) == 3
            and pieces[1].isdigit()
            and 0 <= time.time() - int(pieces[1]) < 1800
            and hmac.compare_digest(
                pieces[2],
                hmac.new(secret, ".".join(pieces[:2]).encode(), hashlib.sha256).hexdigest(),
            )
        )
        session = ".".join(pieces[:2]) if valid else f"{secrets.token_hex(16)}.{int(time.time())}"
        request.state.principal, request.state.role = f"guest:{session}", "guest"
        # Demo traffic must never call external CRM or approve production actions.
        if path.startswith("/crm/") and path != "/crm/notion/status":
            return JSONResponse({"detail": "Demo visitors cannot write to CRM."}, status_code=403)
        if request.method == "POST":
            now = time.monotonic()
            keys = ["all_demo_requests", request.state.principal]
            for key, limit in zip(keys, (200, 20)):
                queue = quotas[key]
                while queue and queue[0] < now - 3600:
                    queue.popleft()
                if len(queue) >= limit:
                    return JSONResponse(
                        {"detail": "Demo hourly limit reached."},
                        status_code=429,
                        headers={"Retry-After": "3600"},
                    )
            for key in keys:
                quotas[key].append(now)
        response = await call_next(request)
        if not valid:
            signature = hmac.new(secret, session.encode(), hashlib.sha256).hexdigest()
            response.set_cookie(
                "leadflow_demo",
                f"{session}.{signature}",
                max_age=1800,
                httponly=True,
                secure=request.url.scheme == "https",
                samesite="strict",
            )
        return response
