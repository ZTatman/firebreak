# Firebreak glossary

A **share link** opens a **snapshot**. A **grant** is the internal record Firebreak checks to decide whether to allow access.

| Term | Meaning | Where it belongs |
| --- | --- | --- |
| **Snapshot** | A repository's content at a specific commit SHA. The branch helps users find a commit; it does not change what a link opens later. | Picker, preview, and viewer copy. A snapshot doesn't need a separate database model. |
| **Share link** | The URL someone copies and sends to let others view a snapshot. | Dashboard copy, share-link API names, and `/links` routes for creating and managing links. |
| **Grant** | The stored access record: the repository and commit SHA, expiration, revocation, and any recipient restriction. | The `Grant` model, `grants` table, and backend authorization code. Use **share link**, not **grant**, in user-facing copy. |

The dashboard's snapshot picker lives under `/dashboard/snapshot-picker`. Reviewing a snapshot in the dialog does not create, publish, or revoke a share link. Existing JSON repository listings stay under `/links/repositories` for compatibility.

Creating a public share link saves a grant for the selected commit, adds a row to the dashboard's Share links table, and displays the URL once. The URL does not open a snapshot until the viewer is implemented.

Revoking a share link records the revocation time on its grant and keeps the record, so the Share links table shows it as Revoked. Only active links can be revoked; an expired link keeps its expiry time.
