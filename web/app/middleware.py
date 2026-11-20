from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response


class SetupRequiredMiddleware(BaseHTTPMiddleware):
    """Redirect all requests to /setup when the app has not been configured yet."""

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if path.startswith("/setup") or path.startswith("/static") or path == "/favicon.ico":
            return await call_next(request)

        if request.app.state.app_settings is None:
            if path.startswith("/links/"):
                return JSONResponse(
                    {"detail": {"stage": "configuration", "message": "Setup required."}},
                    status_code=503,
                    headers={"Cache-Control": "no-store"},
                )
            if request.headers.get("HX-Request"):
                response = Response(status_code=200)
                response.headers["HX-Redirect"] = "/setup"
                return response
            return RedirectResponse("/setup", status_code=302)

        response = await call_next(request)
        if path.startswith("/links/"):
            response.headers["Cache-Control"] = "no-store"
        return response
