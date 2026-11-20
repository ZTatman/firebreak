import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func as sql_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from app import models as _models  # noqa: F401 - register ORM tables on metadata
from app.auth.session import get_current_session, get_optional_session
from app.config import get_settings
from app.database import Base
from app.middleware import SetupRequiredMiddleware
from app.models.app_settings import AppSettings
from app.models.session import Session as UserBrowserSession
from app.routers import auth, links, settings, setup
from app.templating import templates


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage database engine lifecycle and load app settings."""
    boot_settings = get_settings()
    engine = create_async_engine(
        url=boot_settings.database_url,
        pool_pre_ping=True,
        echo=boot_settings.app_name != "Firebreak",
    )
    app.state.db_session = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with app.state.db_session() as db:
        from app.models.user import User

        result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
        row = result.scalar_one_or_none()
        user_count = await db.scalar(select(sql_func.count()).select_from(User))

        app.state.app_settings = row

        # Generate a setup token whenever no users exist yet — whether it's
        # a fresh install or a retry after bad OAuth config.
        if not user_count:
            app.state.setup_token = secrets.token_urlsafe(32)
            logger = logging.getLogger("firebreak")
            logger.warning(
                "\n"
                "╔══════════════════════════════════════════════════════════╗\n"
                "║  SETUP TOKEN (paste this into the setup wizard):        ║\n"
                "║  %-54s  ║\n"
                "╚══════════════════════════════════════════════════════════╝",
                app.state.setup_token,
            )
        else:
            app.state.setup_token = None

    yield
    await engine.dispose()


app = FastAPI(lifespan=lifespan)
app.add_middleware(SetupRequiredMiddleware)

app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.include_router(auth.router)
app.include_router(links.router)
app.include_router(settings.router)
app.include_router(setup.router)

ERROR_TITLES = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    500: "Internal Server Error",
    503: "Service Unavailable",
}


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> Response:
    """Render a styled error page for browser requests, JSON for API clients."""
    accept = request.headers.get("accept", "")
    if "text/html" in accept and not request.url.path.startswith("/links/"):
        return templates.TemplateResponse(
            request,
            "error.html",
            {
                "status_code": exc.status_code,
                "title": ERROR_TITLES.get(exc.status_code, "Error"),
                "detail": exc.detail,
            },
            status_code=exc.status_code,
        )
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> Response:
    if request.url.path.startswith("/links/"):
        errors = [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        return JSONResponse({"detail": errors}, status_code=422)
    return await request_validation_exception_handler(request, exc)


@app.get("/", response_class=HTMLResponse)
async def root(
    request: Request, sess: Annotated[UserBrowserSession | None, Depends(get_optional_session)]
) -> Response:
    return templates.TemplateResponse(
        request,
        "index.html",
        {"user": sess.user if sess else None},
    )


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request, sess: Annotated[UserBrowserSession, Depends(get_current_session)]
) -> Response:
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": sess.user,
            "pat_registered": sess.user.has_pat,
        },
    )
