# Inspect repository and grant JSON

Firebreak exposes repository discovery and public grant creation as authenticated
JSON endpoints. Sign in through Forgejo, then register a PAT from the same account
with `read:user` and `read:repository` scopes in Settings.

The owner check compares Forgejo IDs. Collaborator access, administrator access,
and organization ownership do not qualify. All requests require your active
Firebreak session; inspection data is never exposed through the share URL.

## See what Forgejo returns

While signed in, open `/links/repositories?inspect=true` on your Firebreak host in
the browser. The response includes:

- `repositories`: personally owned repositories normalized for Firebreak
- `inspection.forgejo.authenticated_user`: the PAT-authenticated Forgejo user
- `inspection.forgejo.repositories`: the upstream repository JSON for this page,
  including accessible repositories excluded by the personal-owner filter
- `page`, `limit`, and `next_page`: pagination; request the next page when present

For example, `/links/repositories?inspect=true&page=2&limit=30` inspects page 2.
Pagination follows the upstream page boundaries, so a page can contain no eligible
repositories while still having a `next_page`. Omit `inspect=true` to receive only
the normalized results and pagination.

The inspection payload keeps upstream fields and structure, with credential
fields, credential-bearing URLs, and echoed PAT values redacted. It is returned
only for this request and is not saved in the database. Responses use
`Cache-Control: no-store`.

## Create and inspect a grant

Open `/docs` on the same Firebreak host after signing in. Expand `POST /links/`,
click **Try it out**, set `inspect` to `true`, and supply this body with your own
repository and a future expiration:

```json
{
  "repo_owner": "zach",
  "repo_name": "example",
  "branch": "main",
  "expires_at": "2099-01-01T12:00:00Z",
  "link_type": "public"
}
```

The same-origin request uses your existing browser session. You do not need to
copy a session cookie or paste your PAT into the request. This operation creates
a real grant each time it succeeds; there is no preview/dry-run mode.

The JSON request must use `Content-Type: application/json`. The timestamp must
include a timezone, and the branch must exist. Branch names such as
`feature/example` are supported. Private links and recipient-email fields are
rejected in this slice.

The HTTP 201 response separates:

- `created_grant`: the saved Firebreak record, including its database-generated
  ID and timestamps; `token_hash` is always `[redacted]`
- `share_url`: a freshly generated bearer link, returned once; the database
  contains only the SHA-256 hash of its token
- `viewer_available`: `false`, because `/s/{token}` is not implemented yet
- `inspection`: the validated request, upstream user/repository/branch JSON,
  and the successful ownership decision

The commit SHA comes from Forgejo's `branch.commit.id` and stays pinned even when
the branch moves. Grant creation records expiration, but viewer-side expiration
and revocation enforcement will arrive with the viewer. Treat the one-time share
URL as a secret and keep it out of logs or screenshots you publish.

See [example responses](examples/public-link-inspection.json). These examples
use mocked Forgejo data and a real test database; they are not a capture from
your Forgejo account. IDs/times are illustrative and the one-time share token
has been replaced with `[returned-once]`.

## Failures

| Status | Meaning |
| --- | --- |
| 401 | Missing, expired, or revoked Firebreak session |
| 403 | PAT account mismatch, or repository not personally owned |
| 404 | Forgejo repository or branch not found |
| 409 | No registered PAT |
| 415 | Request did not use `application/json` |
| 422 | Invalid names, expiration, pagination, or unsupported request fields |
| 502 | Forgejo rejected the PAT, was unreachable, or returned invalid data |
| 503 | Setup, public URL, Forgejo transport, or PAT decryption needs attention |
| 500 | Grant could not be saved; transaction rolled back |

Upstream and grant failures include a `detail.stage` and an actionable message.
Failures do not echo raw upstream error bodies, request values, database details,
or partial inspection payloads.

## Run the tests

From the repository root:

```sh
uv --directory web run pytest -q
uv --directory web run mypy app
```

Tests default to an isolated in-memory SQLite database with a mocked Forgejo
transport. For PostgreSQL, set `FIREBREAK_TEST_DATABASE_URL` to a disposable local
test database using the `postgresql+asyncpg://` scheme. Each test creates and drops
its own randomly named schema; the account must have schema-creation privileges.
Tests never use `DATABASE_URL` or contact the configured Forgejo instance.

Upstream reference: [Forgejo API usage](https://forgejo.org/docs/latest/user/api/usage/)
and the instance's `/swagger.v1.json` schema.
