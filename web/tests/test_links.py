import hashlib
import json
from copy import deepcopy
from unittest.mock import AsyncMock

import httpx
import pytest
from conftest import BRANCH_JSON, PAT, REPO_JSON, USER_JSON
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models.grant import Grant
from app.models.session import Session
from app.models.user import LinkedIdentity, User
from app.routers.auth import _parse_user_response


async def grants(api):
    async with api.db() as db:
        return list((await db.scalars(select(Grant))).all())


async def test_create_inspect_persists_exact_snapshot_and_only_hash(api, payload):
    response = await api.client.post("/links/?inspect=true", json=payload)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["viewer_available"] is False
    assert response.headers["cache-control"] == "no-store"
    raw = data["inspection"]["forgejo"]
    assert raw == {"authenticated_user": USER_JSON, "repository": REPO_JSON, "branch": BRANCH_JSON}
    (row,) = await grants(api)
    created = data["created_grant"]
    assert created["id"] == str(row.id)
    assert created["user_id"] == str(api.user_id)
    assert created["commit_sha"] == row.commit_sha == BRANCH_JSON["commit"]["id"]
    assert created["repo_owner"] == row.repo_owner == "zach"
    assert created["repo_name"] == row.repo_name == "example"
    assert created["created_at"] and created["expires_at"]
    assert created["revoked_at"] is None and created["recipient_email"] is None
    token = data["share_url"].rsplit("/", 1)[1]
    assert len(token) >= 43
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert created["token_hash"] == "[redacted]"
    assert row.token_hash not in response.text and PAT not in response.text
    assert token not in json.dumps(created) and token not in json.dumps(data["inspection"])
    assert not hasattr(row, "branch")
    api.routes["/api/v1/repos/zach/example/branches/main"]["commit"]["id"] = "b" * 40
    (row,) = await grants(api)
    assert row.commit_sha == "a" * 40


async def test_inspection_omitted_by_default_and_tokens_unique(api, payload):
    first = await api.client.post("/links/", json=payload)
    second = await api.client.post("/links/", json=payload)
    assert first.status_code == second.status_code == 201
    assert "inspection" not in first.json()
    assert first.json()["share_url"] != second.json()["share_url"]
    response = await api.client.get("/links/repositories")
    assert "inspection" not in response.json()


async def test_repository_discovery_filters_owners_and_exposes_upstream(api):
    collaborator = deepcopy(REPO_JSON)
    collaborator["owner"]["id"] = 99
    api.routes["/api/v1/user/repos"] = [REPO_JSON, collaborator]
    response = await api.client.get("/links/repositories?inspect=true")
    data = response.json()
    assert response.status_code == 200
    assert len(data["repositories"]) == 1
    assert data["repositories"][0]["owner"] == "zach"
    assert data["inspection"]["forgejo"]["repositories"] == [REPO_JSON, collaborator]
    assert data["next_page"] is None


async def test_pagination_does_not_follow_arbitrary_links(api):
    api.routes["/api/v1/user/repos"] = httpx.Response(
        200,
        json=[],
        headers={"Link": '<https://evil.test/?page=2>; rel="next"'},
    )
    response = await api.client.get("/links/repositories?page=1&limit=2")
    assert response.json()["next_page"] == 2
    assert dict(api.calls[-1].url.params) == {"page": "1", "limit": "2"}
    assert len(api.calls) == 2
    api.routes["/api/v1/user/repos"] = [REPO_JSON]
    response = await api.client.get("/links/repositories?page=2&limit=2")
    assert response.json()["page"] == 2
    assert response.json()["repositories"][0]["name"] == "example"


@pytest.mark.parametrize("kind", ["collaborator", "organization", "site_admin"])
async def test_non_owner_rejected_even_with_admin_access(api, payload, kind):
    api.routes["/api/v1/repos/zach/example"]["owner"]["id"] = 99
    api.routes["/api/v1/user"]["is_admin"] = kind == "site_admin"
    response = await api.client.post("/links/?inspect=true", json=payload)
    assert response.status_code == 403
    assert response.json()["detail"]["stage"] == "repository"
    assert len(api.calls) == 2
    assert not await grants(api)


@pytest.mark.parametrize("path", ["/links/", "/links/repositories"])
async def test_pat_identity_mismatch(api, payload, path):
    api.routes["/api/v1/user"]["id"] = 999
    response = (
        await api.client.post(path, json=payload)
        if path == "/links/"
        else await api.client.get(path)
    )
    assert response.status_code == 403
    assert response.json()["detail"]["stage"] == "identity"
    assert len(api.calls) == 1
    assert not await grants(api)


async def test_missing_linked_identity_rejected(api, payload):
    async with api.db() as db:
        identity = await db.scalar(select(LinkedIdentity))
        await db.delete(identity)
        await db.commit()
    response = await api.client.post("/links/", json=payload)
    assert response.status_code == 403
    assert not await grants(api)


@pytest.mark.parametrize("pat,status", [(None, 409), ("invalid-ciphertext", 503)])
async def test_missing_or_corrupt_pat(api, payload, pat, status):
    async with api.db() as db:
        user = await db.get(User, api.user_id)
        user.pat_encrypted = pat
        await db.commit()
    response = await api.client.post("/links/", json=payload)
    assert response.status_code == status
    assert not api.calls
    assert not await grants(api)


async def test_signed_out_browser_receives_json(api, payload):
    api.client.cookies.clear()
    for response in [
        await api.client.get("/links/repositories", headers={"Accept": "text/html"}),
        await api.client.post("/links/", json=payload, headers={"Accept": "text/html"}),
    ]:
        assert response.status_code == 401
        assert response.headers["content-type"] == "application/json"
        assert response.headers["cache-control"] == "no-store"
    assert not api.calls


@pytest.mark.parametrize(
    "changes",
    [
        {"link_type": "private"},
        {"recipient_email": "test@example.test"},
        {"expires_at": "2000-01-01T00:00:00Z"},
        {"expires_at": "2099-01-01T00:00:00"},
        {"repo_owner": ".."},
        {"repo_name": "../user"},
        {"branch": "../user"},
        {"branch": "main?token=evil"},
        {"branch": ""},
        {"branch": "main\n"},
    ],
)
async def test_invalid_requests_do_not_create_grants(api, payload, changes):
    response = await api.client.post("/links/", json={**payload, **changes})
    assert response.status_code == 422
    assert not api.calls
    assert not await grants(api)


async def test_form_content_rejected_and_validation_does_not_echo_secrets(api, payload):
    response = await api.client.post("/links/", data={**payload, "pat": PAT})
    assert response.status_code == 415
    response = await api.client.post("/links/", json={**payload, "pat": PAT})
    assert response.status_code == 422
    assert PAT not in response.text


async def test_slash_branch_encoded_and_timezone_normalized(api, payload):
    api.routes["/api/v1/repos/zach/example/branches/feature/hello"] = {
        "name": "feature/hello",
        "commit": {"id": "c" * 40},
    }
    payload["branch"] = "feature/hello"
    payload["expires_at"] = "2099-01-01T08:00:00-05:00"
    response = await api.client.post("/links/", json=payload)
    assert response.status_code == 201, response.text
    assert b"feature%2Fhello" in api.calls[-1].url.raw_path
    assert response.json()["created_grant"]["expires_at"].startswith("2099-01-01T13:00:00")


@pytest.mark.parametrize(
    "path,body",
    [
        ("/api/v1/user", {}),
        ("/api/v1/user", {"id": True, "login": "zach"}),
        ("/api/v1/repos/zach/example", {"owner": {"id": 17}}),
        ("/api/v1/repos/zach/example/branches/main", {"name": "main", "commit": {"id": "main"}}),
        ("/api/v1/repos/zach/example/branches/main", {"name": "wrong", "commit": {"id": "a" * 40}}),
        ("/api/v1/repos/zach/example/branches/main", []),
    ],
)
async def test_malformed_upstream_fails_closed(api, payload, path, body):
    api.routes[path] = body
    response = await api.client.post("/links/", json=payload)
    assert response.status_code == 502
    assert not await grants(api)


@pytest.mark.parametrize(
    "status,expected", [(401, 502), (403, 502), (404, 404), (500, 502), (302, 502)]
)
async def test_forgejo_http_errors_do_not_reflect_credentials(api, payload, status, expected):
    api.routes["/api/v1/repos/zach/example"] = httpx.Response(
        status,
        json={"message": PAT},
        headers={"Location": "https://evil.test"},
    )
    response = await api.client.post("/links/?inspect=true", json=payload)
    assert response.status_code == expected
    assert PAT not in response.text
    assert len(api.calls) == 2
    assert not await grants(api)


@pytest.mark.parametrize(
    "reply", [httpx.ReadTimeout("secret upstream detail"), httpx.Response(200, text="invalid JSON")]
)
async def test_transport_and_json_errors(api, payload, reply):
    api.routes["/api/v1/user"] = reply
    response = await api.client.post("/links/", json=payload)
    assert response.status_code == 502
    assert "secret upstream detail" not in response.text
    assert not await grants(api)


async def test_redaction_preserves_noncredential_payload_fields(api, payload):
    api.routes["/api/v1/repos/zach/example"].update(
        {
            "token": "raw-token",
            "nested": [{"password": "raw-password", "note": PAT}],
            "clone_url": "https://user:raw-password@git.example.test/repo",
        }
    )
    response = await api.client.post("/links/?inspect=true", json=payload)
    assert response.status_code == 201
    assert all(secret not in response.text for secret in [PAT, "raw-token", "raw-password"])
    raw = response.json()["inspection"]["forgejo"]["repository"]
    assert raw["description"] == REPO_JSON["description"]
    assert raw["token"] == raw["nested"][0]["password"] == "[redacted]"


@pytest.mark.parametrize("method", ["flush", "commit"])
async def test_database_failure_rolls_back(api, payload, monkeypatch, method):
    original = getattr(AsyncSession, method)
    rollback = AsyncMock(wraps=None)
    original_rollback = AsyncSession.rollback

    async def fail_grant(session, *args, **kwargs):
        if any(isinstance(obj, Grant) for obj in session.new) or session.info.get("grant_flushed"):
            raise SQLAlchemyError("private database detail")
        return await original(session, *args, **kwargs)

    if method == "commit":
        original_flush = AsyncSession.flush

        async def track_grant(session, *args, **kwargs):
            if any(isinstance(obj, Grant) for obj in session.new):
                session.info["grant_flushed"] = True
            return await original_flush(session, *args, **kwargs)

        monkeypatch.setattr(AsyncSession, "flush", track_grant)

    async def record_rollback(session):
        await rollback()
        await original_rollback(session)

    monkeypatch.setattr(AsyncSession, method, fail_grant)
    monkeypatch.setattr(AsyncSession, "rollback", record_rollback)
    response = await api.client.post("/links/?inspect=true", json=payload)
    assert response.status_code == 500, response.text
    assert "private database detail" not in response.text
    rollback.assert_awaited_once()
    assert not await grants(api)


@pytest.mark.parametrize(
    "base", ["", "https://user:password@share.test", "https://share.test?query=1"]
)
async def test_invalid_public_url_does_not_persist(api, payload, base):
    api.settings.firebreak_public_base_url = base
    response = await api.client.post("/links/", json=payload)
    assert response.status_code == 503
    assert not await grants(api)


def test_oauth_parser_accepts_documented_login_field():
    assert _parse_user_response(USER_JSON) == ("17", "zach", "zach@example.test")


@pytest.mark.parametrize("revoked", [False, True])
async def test_expired_or_revoked_sessions_rejected(api, payload, revoked):
    from datetime import UTC, datetime, timedelta

    async with api.db() as db:
        session = await db.scalar(select(Session))
        if revoked:
            session.revoked_at = datetime.now(UTC)
        else:
            session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
    response = await api.client.post("/links/", json=payload)
    assert response.status_code == 401
    assert not await grants(api)


async def test_unconfigured_app_returns_json(api):
    app.state.app_settings = None
    response = await api.client.get("/links/repositories", headers={"Accept": "text/html"})
    assert response.status_code == 503
    assert response.json()["detail"]["stage"] == "configuration"


@pytest.mark.parametrize("body", [{"data": []}, [{"name": "incomplete"}]])
async def test_malformed_discovery(api, body):
    api.routes["/api/v1/user/repos"] = body
    response = await api.client.get("/links/repositories?inspect=true")
    assert response.status_code == 502
    assert response.json()["detail"]["stage"] == "repositories"


async def test_unimplemented_viewer_is_explicit(api, payload):
    created = await api.client.post("/links/", json=payload)
    assert created.status_code == 201
    assert created.json()["viewer_available"] is False
    path = httpx.URL(created.json()["share_url"]).path
    response = await api.client.get(path)
    assert response.status_code == 404
