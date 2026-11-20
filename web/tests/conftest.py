import hashlib
import os
import uuid
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_fernet, get_settings
from app.database import Base
from app.main import app
from app.models.app_settings import AppSettings
from app.models.session import Session
from app.models.user import LinkedIdentity, User
from app.services import forgejo

PAT = "test-pat-must-never-be-returned"
COOKIE = "test-session-token"
USER_JSON = {"id": 17, "login": "zach", "email": "zach@example.test", "is_admin": False}
REPO_JSON = {
    "id": 91,
    "owner": USER_JSON,
    "name": "example",
    "full_name": "zach/example",
    "default_branch": "main",
    "private": True,
    "permissions": {"pull": True, "admin": True},
    "description": "Preserve this unmodeled upstream field",
}
BRANCH_JSON = {"name": "main", "commit": {"id": "a" * 40, "message": "Example commit"}}


@pytest.fixture
async def api(monkeypatch):
    cipher = Fernet(Fernet.generate_key())
    monkeypatch.setattr("app.auth.pat.get_fernet", lambda: cipher)
    database_url = os.environ.get("FIREBREAK_TEST_DATABASE_URL", "sqlite+aiosqlite://")
    engine = create_async_engine(database_url)
    schema = "test_inspection_" + uuid.uuid4().hex
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine.sync_engine, "connect")
        def sqlite_functions(connection, _):
            connection.create_function("gen_random_uuid", 0, lambda: uuid.uuid4().hex)
            connection.execute("PRAGMA foreign_keys=ON")
    else:
        async with engine.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = engine.execution_options(schema_translate_map={None: schema})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    user_id = uuid.uuid4()
    async with sessionmaker() as db:
        db.add(
            User(
                id=user_id, display_name="zach", pat_encrypted=cipher.encrypt(PAT.encode()).decode()
            )
        )
        await db.flush()
        db.add_all(
            [
                LinkedIdentity(
                    user_id=user_id,
                    provider="forgejo",
                    provider_user_id="17",
                    provider_username="old-name",
                ),
                Session(
                    user_id=user_id,
                    token_hash=hashlib.sha256(COOKIE.encode()).hexdigest(),
                    expires_at=datetime.now(UTC) + timedelta(days=1),
                ),
            ]
        )
        await db.commit()
    settings = AppSettings(
        forgejo_base_url="https://forgejo.example.test",
        firebreak_public_base_url="https://share.example.test",
    )
    routes = {
        "/api/v1/user": deepcopy(USER_JSON),
        "/api/v1/user/repos": [deepcopy(REPO_JSON)],
        "/api/v1/repos/zach/example": deepcopy(REPO_JSON),
        "/api/v1/repos/zach/example/branches/main": deepcopy(BRANCH_JSON),
    }
    calls = []

    def upstream(request):
        calls.append(request)
        assert request.headers["Authorization"] == f"token {PAT}"
        reply = routes[request.url.path]
        if isinstance(reply, Exception):
            raise reply
        if callable(reply):
            reply = reply(request)
        return reply if isinstance(reply, httpx.Response) else httpx.Response(200, json=reply)

    async def forgejo_client():
        async with httpx.AsyncClient(
            base_url=forgejo.validate_base_url(settings.forgejo_base_url) + "/api/v1/",
            transport=httpx.MockTransport(upstream),
            follow_redirects=False,
        ) as client:
            yield client

    app.state.db_session = sessionmaker
    app.state.app_settings = settings
    app.dependency_overrides[forgejo.get_client] = forgejo_client
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://firebreak.example.test",
        cookies={"firebreak_session": COOKIE},
    ) as client:
        yield SimpleNamespace(
            client=client,
            db=sessionmaker,
            routes=routes,
            calls=calls,
            user_id=user_id,
            settings=settings,
            cipher=cipher,
        )
    app.dependency_overrides.clear()
    if engine.dialect.name != "sqlite":
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    await engine.dispose()
    get_settings.cache_clear()
    get_fernet.cache_clear()


@pytest.fixture
def payload():
    return {
        "repo_owner": "zach",
        "repo_name": "example",
        "branch": "main",
        "expires_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
        "link_type": "public",
    }
