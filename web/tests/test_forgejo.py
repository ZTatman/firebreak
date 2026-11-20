import httpx
import pytest
from fastapi import HTTPException

from app.models.app_settings import AppSettings
from app.services.forgejo import get, get_client, validate_base_url
from app.services.inspection import redact


@pytest.mark.parametrize(
    "url",
    [
        "http://git.example.test",
        "ftp://git.example.test",
        "https://user:pass@git.example.test",
        "https://git.example.test?token=secret",
        "https://git.example.test#fragment",
        "",
        "/api",
        "https://git.example.test:bad",
        "http://localhost.evil.test",
        "http://127.0.0.1.evil.test",
    ],
)
def test_rejects_insecure_or_ambiguous_forgejo_urls(url):
    with pytest.raises(HTTPException) as error:
        validate_base_url(url)
    assert error.value.status_code == 503
    assert "pass@" not in str(error.value.detail)


@pytest.mark.parametrize(
    "url",
    [
        "https://git.example.test/forgejo",
        "http://forgejo:3000",
        "http://localhost:3000",
        "http://git.localhost:3000",
        "http://127.0.0.1:3000",
        "http://[::1]:3000",
    ],
)
def test_preserves_documented_local_http_exceptions(url):
    assert validate_base_url(url + "/") == url


async def test_client_uses_configured_subpath_and_disables_redirects():
    settings = AppSettings(forgejo_base_url="https://git.example.test/forgejo/")
    dependency = get_client(settings)
    client = await anext(dependency)
    try:
        assert str(client.base_url) == "https://git.example.test/forgejo/api/v1/"
        assert client.follow_redirects is False
        assert client.timeout.read == 10
    finally:
        await dependency.aclose()


async def test_get_preserves_body_and_query_parameters():
    seen = []

    def upstream(request):
        seen.append(request)
        return httpx.Response(200, json=[{"unmodeled": "preserved"}])

    async with httpx.AsyncClient(
        base_url="https://git.example.test/forgejo/api/v1/",
        transport=httpx.MockTransport(upstream),
    ) as client:
        body, response = await get(
            client, "user/repos", "test-pat", "repositories", params={"page": 2}
        )
    assert body == [{"unmodeled": "preserved"}]
    assert seen[0].url.path == "/forgejo/api/v1/user/repos"
    assert seen[0].headers["Authorization"] == "token test-pat"
    assert seen[0].url.params["page"] == "2"
    assert response.status_code == 200


def test_redaction_handles_nested_credentials_and_url_query():
    body = {
        "items": [{"oauth_secret": "secret", "pat_encrypted": "ciphertext"}],
        "url": "https://user:password@git.test/repo?token=secret&ref=main",
        "message": "PAT echoed here: known-pat",
        "safe": 17,
    }
    result = redact(body, "known-pat")
    assert result["safe"] == 17
    assert result["items"][0] == {"oauth_secret": "[redacted]", "pat_encrypted": "[redacted]"}
    assert result["url"] == "https://[redacted]@git.test/repo?token=[redacted]&ref=main"
    assert result["message"] == "PAT echoed here: [redacted]"
    assert body["items"][0]["oauth_secret"] == "secret"
