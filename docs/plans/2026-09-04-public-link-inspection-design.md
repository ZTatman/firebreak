# Public Link Inspection Design

## Goal

Build the first API-only slice of Firebreak's public share-link flow. The slice
must prove that Firebreak can authenticate a Forgejo user, identify repositories
that user personally owns, resolve a branch to an immutable commit, and persist a
public grant. It must expose the relevant JSON so the Forgejo payloads and the
created Firebreak record can be inspected before any code viewer is designed.

This PR does not implement a repository tree or file viewer.

## Scope

The PR includes:

- authenticated discovery of personally owned Forgejo repositories
- verification that the registered PAT belongs to the signed-in Forgejo identity
- server-side repository ownership verification
- branch-to-commit resolution
- public grant creation using an opaque share token
- raw Forgejo response inspection behind an explicit query parameter
- a normalized representation of eligible repositories and the created grant
- automated tests for the API, ownership boundary, token handling, and failures

The PR excludes:

- HTML, HTMX, or other link-creation UI
- repository tree or file rendering
- private links and email verification
- organization-owned repositories
- access logs and view counts
- grant revocation UI
- persistence of raw Forgejo responses

## Ownership Rule

Phase 1 supports personally owned repositories only.

Firebreak calls Forgejo's authenticated-user endpoint using the registered PAT
and compares that Forgejo user ID with the user's linked Forgejo OAuth identity.
The PAT is rejected if the IDs differ. For a selected repository, Firebreak then
requires the repository owner's Forgejo user ID to equal the authenticated PAT
user's ID. Pull, push, collaborator, administrator, or site-administrator access
does not satisfy this rule.

This check is performed server-side when the grant is created. A client-provided
owner name is never treated as proof of ownership.

## API

### Discover repositories

`GET /links/repositories?inspect=true`

The route requires an active Firebreak session and a registered Forgejo PAT. It
fetches the authenticated Forgejo user and that user's repositories, applies the
personal-ownership rule, and returns:

```json
{
  "repositories": [
    {
      "owner": "zach",
      "name": "example",
      "full_name": "zach/example",
      "default_branch": "main",
      "private": true
    }
  ],
  "page": 1,
  "limit": 30,
  "next_page": null,
  "inspection": {
    "forgejo": {
      "authenticated_user": {},
      "repositories": []
    }
  }
}
```

`repositories` is the normalized Firebreak contract. `inspection` is included
only when `inspect=true` and preserves JSON fields received from Forgejo after
response parsing, except for credential redaction. Discovery accepts `page` and
`limit` and reports `next_page` using Forgejo's pagination header. Firebreak does
not persist the inspection data.

### Create a public grant

`POST /links/?inspect=true`

Request:

```json
{
  "repo_owner": "zach",
  "repo_name": "example",
  "branch": "main",
  "expires_at": "2026-09-11T12:00:00Z",
  "link_type": "public"
}
```

The route accepts public grants only. `expires_at` must be timezone-aware and in
the future. Firebreak fetches the authenticated Forgejo user, repository, and
branch; verifies identity and ownership; resolves the branch to its commit SHA;
and creates the grant in one database transaction.

Successful response: HTTP 201.

```json
{
  "created_grant": {
    "id": "2d792f51-10a7-46cf-9b88-7a0c9f6ea769",
    "repo_owner": "zach",
    "repo_name": "example",
    "commit_sha": "abc123",
    "grant_type": "public",
    "created_at": "2026-09-04T12:00:00Z",
    "expires_at": "2026-09-11T12:00:00Z",
    "revoked_at": null,
    "recipient_email": null,
    "token_hash": "[redacted]"
  },
  "share_url": "https://share.example.com/s/opaque-token",
  "viewer_available": false,
  "inspection": {
    "request": {
      "repo_owner": "zach",
      "repo_name": "example",
      "branch": "main",
      "expires_at": "2026-09-11T12:00:00Z"
    },
    "forgejo": {
      "authenticated_user": {},
      "repository": {},
      "branch": {}
    },
    "ownership": {
      "allowed": true,
      "reason": "repository owner matches authenticated Forgejo user"
    }
  }
}
```

`created_grant` mirrors the persisted database record except that the token hash
is always represented as `[redacted]`. The usable share URL is returned once.
Its viewer endpoint is intentionally unavailable in this PR, which is made
explicit by `viewer_available: false`.

## Token Handling

Firebreak generates a cryptographically random URL-safe token. The raw token is
used only to construct the one-time response URL. Firebreak stores a SHA-256 hash
in `Grant.token_hash`; it never stores the raw token.

Inspection responses never contain PATs, OAuth credentials, encryption keys,
authorization headers, or the stored token hash. Raw Forgejo JSON bodies are
returned only to the authenticated Firebreak user that requested inspection.

## Components

- A thin Forgejo service owns HTTP mechanics, URL construction, response parsing,
  and typed upstream failures.
- A token helper pairs PAT decryption with the current application cipher.
- The links router owns request validation, session enforcement, ownership
  decisions, grant construction, and response serialization.
- Pydantic response models separate the stable Firebreak contract from optional
  inspection payloads.
- The existing `Grant` model remains the persisted source of truth. Raw Forgejo
  responses and branch names are not stored.

## Error Handling

- `401` when there is no active Firebreak session
- `409` when the signed-in user has not registered a PAT
- `403` when the PAT identity differs from the OAuth identity or the repository
  is not personally owned by that identity
- `404` when Forgejo cannot find the selected repository or branch
- `422` for unsupported link types, invalid names, naive timestamps, or an
  expiration that is not in the future
- `502` when Forgejo is unreachable, returns an unexpected response, or rejects
  an otherwise valid upstream request
- `500` for a failed database transaction, after rollback and without exposing
  database details

Failures identify the stage (`identity`, `repositories`, `repository`, `branch`,
or `grant`) without exposing credentials. Partial upstream inspection payloads
are omitted on failure.

## Testing

Tests use mocked Forgejo HTTP responses and a test database/session dependency.
They cover:

- repository discovery returns raw and normalized JSON
- inspection data is absent unless requested
- the PAT user ID must match the linked OAuth identity ID
- collaborators and other non-owner users are rejected
- a personally owned repository is accepted
- a branch is pinned to the exact Forgejo commit SHA
- only a token hash is persisted
- the raw token appears only in the one-time share URL
- past or timezone-naive expirations are rejected
- Forgejo transport, authentication, not-found, and malformed-payload failures
- database failure rolls back without returning a created grant

## Follow-up Boundary

The next PR can use the persisted grant and returned share token to implement
viewer-side lookup and expiration/revocation enforcement. Tree shape and file
payload decisions will be based on observed Forgejo JSON from this inspection
slice rather than assumptions made in advance.
