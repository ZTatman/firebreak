# Public Link Inspection Implementation Plan

## Objective

Implement and verify the approved API-only public-link inspection slice without
adding a code viewer or link-creation UI.

## 1. Establish the test harness

- Add the minimum Python test dependencies needed for FastAPI route and async
  service tests.
- Add fixtures for an authenticated Firebreak session, linked Forgejo identity,
  registered encrypted PAT, application settings, and database session.
- Provide mocked Forgejo HTTP responses without contacting a live service.
- Confirm the empty baseline test suite, Ruff, and mypy run locally.

## 2. Centralize Forgejo API access

- Add a thin `app.services.forgejo` client for authenticated GET requests.
- Preserve parsed upstream JSON so the router can return inspection data.
- Define typed failures that retain safe status and stage information.
- Test URL construction, authentication headers, non-2xx responses, malformed
  JSON, and transport errors.

## 3. Add application-aware PAT access

- Add one helper that decrypts the signed-in user's PAT through the configured
  Fernet cipher.
- Convert missing PAT and decryption failures into explicit route-level errors.
- Ensure no exception or response contains the raw PAT.

## 4. Implement identity and ownership checks

- Fetch the PAT-authenticated Forgejo user.
- Load the signed-in user's Forgejo linked identity and compare immutable Forgejo
  user IDs.
- Fetch repository metadata and require its owner ID to match that user ID.
- Reject collaborators, administrators, organization repositories, and PAT/OAuth
  identity mismatches.
- Add focused tests for every allow and deny case.

## 5. Implement repository discovery JSON

- Add `GET /links/repositories` behind the current session dependency.
- Return a normalized list of personally owned repositories.
- Add optional raw `inspection.forgejo` fields when `inspect=true`.
- Verify the inspection envelope is omitted by default and contains no secrets.

## 6. Implement public grant creation

- Replace the 501 handler with an authenticated HTTP 201 route.
- Restrict the accepted link type to `public` and require a future,
  timezone-aware expiration.
- Fetch and verify repository metadata, then fetch the requested branch.
- Extract the immutable commit SHA from the branch response.
- Generate a URL-safe token, hash it with SHA-256, and create the existing
  `Grant` record in a single transaction.
- Refresh the created row so server-generated ID and timestamps are returned.
- Build the future share URL from the configured Firebreak public base URL.

## 7. Serialize created and inspection data

- Return a stable `created_grant`, `share_url`, and `viewer_available: false`.
- Represent `token_hash` as `[redacted]`; never serialize the stored hash.
- When `inspect=true`, include the request, raw Forgejo user/repository/branch
  responses, and the ownership decision.
- Add response-model tests that fail if credentials or hashes appear.

## 8. Complete error and transaction coverage

- Map missing session, missing PAT, identity mismatch, ownership denial,
  repository/branch not found, upstream failures, invalid expiration, and
  database failure to the approved status codes.
- Roll back failed writes and confirm no grant remains after an error.
- Keep messages actionable while avoiding upstream credentials and database
  details.

## 9. Validate and document the observed payloads

- Run the complete Python test suite, Ruff, mypy, and template checks affected by
  the change.
- Exercise the routes against the configured development Forgejo instance when
  available and capture representative redacted JSON in the PR description.
- Update the Phase 1 progress list only for behavior proven by the final tests.
- Record any newly discovered repository-specific obstacle in `agents.md` before
  completing the PR.
