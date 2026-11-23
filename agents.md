# agents.md

This file is the single source of truth for codebase obstacles, oddities, and their resolutions. Do not scatter this knowledge in comments, commit messages, or memory.

---

## Rules for agents

1. **Before solving a problem**, check this file. If the problem is documented, use the recorded solution or workaround. Do not re-derive it.
2. **After solving a new problem**, document it here before moving on. Keep entries concise.
3. **Do not deviate** from a recorded solution without first confirming with the user. Once confirmed, update this file with the new approach and reason before proceeding.

---

## Entry format

```text
### [Short problem title]
**Area:** [file, module, or system this affects]
**Obstacle:** What the problem is and where it appears.
**Solution/Workaround:** What was done to fix or work around it.
**Preference:** If multiple approaches exist, which was chosen and why.
```

---

## Documented obstacles

### Shared dependency aliases created circular imports
**Area:** web/app/deps.py, web/app/auth/session.py, web/app/settings.py
**Obstacle:** Moving session aliases into deps.py made it import auth/session.py, which already imports get_db from deps.py. Renaming config.py to settings.py also left stale imports.
**Solution/Workaround:** Keep get_db in deps.py and dependency aliases local to their consuming modules. Update imports to app.settings and import AppSettings directly from app.models.app_settings.
**Preference:** Keep dependency wiring simple while building the feature; defer shared alias extraction.

### TypeScript composite builds fail with no output
**Area:** cli/tsconfig.json, tsconfig.base.json
**Obstacle:** When `composite: true` is set in tsconfig, TypeScript requires proper project references to build. The CLI package was building but producing no output files, causing "cannot find module" errors.
**Solution:** Remove `composite: true` from cli/tsconfig.json. Also removed `noUncheckedIndexedAccess` and `exactOptionalPropertyTypes` from tsconfig.base.json as they caused strict type issues with dynamic config objects.
**Preference:** Use simple tsconfig without composite mode for CLI package.

### verify.ts overly complex abstraction
**Area:** cli/src/commands/verify.ts
**Obstacle:** Code had too many layers: collectResults → addResult (inner function) → displayDiagnosticResults/verifyResults. Made it hard to trace and debug.
**Solution:** Rewrote to be flatter: verifyCommand → runDiagnosticMode/runVerifyMode. Used simple inline logic instead of adding functions for everything.
**Preference:** KISS - keep functions small but avoid over-abstraction.

### Error messages in forgejo-checks too generic
**Area:** cli/src/utils/forgejo-checks.ts
**Obstacle:** Network errors showed "fetch failed" with no context. HTTP errors showed just status codes. Not actionable for users.
**Solution:** Added getErrorMessage() helper to detect: timeouts, connection refused, host not found. Improved HTTP error messages to include status text. Added context prefixes like "cannot reach server", "cannot connect to API".
**Preference:** Actionable messages that tell users what to fix.

### ENV_MAPPING duplicated inline in verify.ts
**Area:** cli/src/commands/verify.ts
**Obstacle:** Had duplicate object with same keys as ENV_MAPPING from config.ts. Two sources of truth.
**Solution:** Import ENV_MAPPING and use it. Change display to show env var names (SNAKE_CASE) instead of internal keys.
**Preference:** Single source of truth in config.ts.

### Display verbiage redundancy
**Area:** cli/src/commands/verify.ts
**Obstacle:** Displayed "MYST_PUBLIC_URL set" - "set" is redundant, icon already shows status.
**Solution:** Just show env var name, remove "set".
**Preference:** Cleaner, let icon indicate status.

### loadConfig returning wrong type for error case
**Area:** cli/src/commands/verify.ts  
**Obstacle:** loadConfig() threw error when .env not found, but caught and re-threw in verifyCommand. This caused process to exit with stack trace instead of clean message.
**Solution:** Return null on ENOENT, handle null in verifyCommand. Return type: `Record<string, string> | null`.
**Preference:** Explicit null handling over exceptions for user-facing errors.

### Logout cookie not reaching browser
**Area:** web/app/routers/auth.py, web/app/auth/session.py
**Obstacle:** `revoke_session` set cookies on the injected `Response` parameter, but the logout handler returned a new `RedirectResponse` — so `Set-Cookie` was discarded.
**Solution:** Create `RedirectResponse` first, then pass it into `revoke_session`. Same pattern used in `callback_forgejo` for `create_session`.
**Preference:** Pass the actual response object that will be returned.

### crypto.py decrypt functions kept proactively
**Area:** web/app/auth/crypto.py
**Obstacle:** CodeRabbit flagged missing decryption functions and key validation. Added `decrypt_token`/`decrypt_optional` + key format validation in `fernet_from_encryption_key`.
**Solution:** Added the functions even though no consumer exists yet. They will be used for PAT decryption in share link flow.
**Preference:** Keep dead code if it's small, symmetric (`encrypt`/`decrypt`), and has an obvious future consumer.

### User model Session import direct instead of TYPE_CHECKING
**Area:** web/app/models/user.py
**Obstacle:** `Session` was imported directly (`from .session import Session`) while `Grant` used `TYPE_CHECKING`. Inconsistent and risked circular imports.
**Solution:** Moved `Session` import under `TYPE_CHECKING`, changed relationship to string ref `"Session"`.
**Preference:** Always use `TYPE_CHECKING` for model references within models to avoid circular imports.

### Boilerplate UI must follow attached light vault system
**Area:** web/app/static/css/input.css, web/app/templates/*.html
**Obstacle:** Existing boilerplate used dark-mode pink tokens that conflicted with the attached "Mystique Minimalist Security" design system.
**Solution/Workaround:** Use light Geist/JetBrains Mono typography, glacier-blue primary actions, white/off-white tonal surfaces, hairline slate borders, compact labels, mono technical strings, and pill status badges.
**Preference:** Keep visual changes in Tailwind tokens and boilerplate templates; avoid backend route changes for design-only updates.

### Tailwind design tokens should use paired semantic roles
**Area:** web/app/static/css/input.css, web/app/templates/*.html
**Obstacle:** Early UI templates mixed old role names (`background-*`, `text-*`, `stroke`) and hardcoded `white` values inside component classes, which made dark mode and future theming brittle.
**Solution/Workaround:** Use Tailwind v4 `@theme` tokens with semantic pairs such as `background/foreground`, `card/card-foreground`, `primary/primary-foreground`, `secondary/secondary-foreground`, `border`, `input`, and `ring`. Keep shared component structure in base classes like `.btn`, with variant classes only setting semantic colors.
**Preference:** Prefer semantic token names over appearance-based names; add dark mode by overriding CSS variables under `.dark`.

### Header brand SVG inherits unwanted icon styling
**Area:** web/app/templates/base.html, web/app/templates/index.html, web/app/static/css/input.css
**Obstacle:** The inline Firebreak header wordmark uses hardcoded SVG fills, and page-level header rules can accidentally apply icon `stroke` styles to the brand SVG. On forced-dark landing headers, the `#17191C` wordmark fill disappears against the obsidian nav.
**Solution/Workaround:** Give the header brand link a stable `brand-link` class, prevent inherited SVG strokes on `.brand-link svg`, and override only the hardcoded wordmark fill in dark contexts or forced-dark page headers.
**Preference:** Scope icon stroke rules to nav icons; do not apply broad `header svg` stroke styles.

### Landing video poster caused logo flash
**Area:** web/app/templates/index.html, web/app/static/img/
**Obstacle:** Using a logo SVG as the `<video poster>` made the browser briefly stretch the logo across the full hero video area before the MP4 painted, which looked like the center logo flashing huge on refresh.
**Solution/Workaround:** Use a real video-frame poster image (`firebreak-hero-poster.jpg`) or omit `poster`; do not use logo assets as full-bleed video posters.
**Preference:** Keep logo sizing in the logo `<img>` and use a frame still for video loading states.

### POST forms lack CSRF tokens
**Area:** web/app/routers/setup.py, web/app/routers/settings.py, web/app/templates/setup.html, web/app/templates/settings.html
**Obstacle:** All state-changing forms (`/setup`, `/settings/pat`, `/settings/pat/delete`) use plain POST with no CSRF token. SameSite=Lax on the session cookie mitigates most cross-origin attacks, but does not fully cover same-site subdomain scenarios.
**Solution/Workaround:** Deferred. Low practical risk since Firebreak runs behind a VPN. Add server-generated CSRF tokens (hidden form field + server-side check) before exposing the app to the public internet.
**Preference:** Use a FastAPI CSRF middleware or manual double-submit cookie pattern when addressing this.

### Firebreak UI is currently dark-only
**Area:** web/app/templates/base.html, web/app/static/css/input.css
**Obstacle:** Theme switching and persisted localStorage theme state conflicted with the current Firebreak brand pass, especially on the cinematic landing page.
**Solution/Workaround:** Force the root document to use the `.dark` token set and remove the theme toggle UI/scripts.
**Preference:** Keep semantic dark tokens; only reintroduce theme switching after the dark Firebreak identity is stable.

### Forgejo repository check accepted empty accounts
**Area:** cli/src/utils/forgejo-checks.ts
**Obstacle:** `checkRepoAccess` treated any parsed user object as success, even when Forgejo reported zero accessible repositories.
**Solution/Workaround:** Require `totalRepos > 0` before returning the existing success result; preserve the existing zero-repository failure.
**Preference:** A valid token alone is insufficient for repository-access verification.

### Forgejo PAT could be sent over remote HTTP
**Area:** cli/src/utils/forgejo-checks.ts, cli/src/commands/config/init.ts, web/app/clients/forgejo.py
**Obstacle:** Accepting remote `http://` Forgejo URLs allowed credentials to be sent without transport encryption.
**Solution/Workaround:** Require HTTPS for non-local endpoints and allow HTTP only for the documented `forgejo` service and loopback hosts. Validate at each client boundary before sending credentials.
**Preference:** Reject insecure remote transport instead of adding an acknowledgement flag.

### Tailwind standalone CLI was killed by macOS code signing
**Area:** web/tailwindcss, web/dev.sh
**Obstacle:** The downloaded standalone Tailwind binary is ad-hoc ("linker-signed") only. macOS AMFI rejected it with `has no CMS blob` / `Unrecoverable CT signature issue`, and the kernel denied the page at offset `0x4b00000` and sent SIGKILL. `dev.sh` uses `set -euo pipefail`, so the script aborted silently with exit 137 and no error message.
**Solution/Workaround:** Resolved by migrating the web CSS build to pnpm (`@tailwindcss/cli`), which ships a normally signed binary. If the standalone binary is ever re-downloaded, fix with `xattr -c web/tailwindcss && codesign --force --sign - web/tailwindcss`. Diagnose this class of failure with `/usr/bin/log show --predicate 'eventMessage CONTAINS[c] "tailwind"'`.
**Preference:** Prefer the pnpm-managed CLI; do not re-add the standalone binary.

### Tailwind watcher can stop on stdin
**Area:** web/dev.sh, web/package.json (`css:watch` script)
**Obstacle:** With job control enabled, the background watcher can stop on SIGTTIN when bare `--watch` reads terminal stdin. With closed stdin it instead exits after the first build.
**Solution/Workaround:** Redirect the background watcher's stdin to `/dev/null` and use `--watch=always`. Keep process-group cleanup in `dev.sh`.
**Preference:** Keep the watcher independent of terminal input. For an isolated smoke check, run the installed CLI against temporary CSS rather than linking the workspace's `node_modules` into a separate pnpm project.

### pnpm install failed with exit 1 on blocked build scripts
**Area:** pnpm-workspace.yaml
**Obstacle:** pnpm 10 does not run dependency lifecycle scripts unless allowlisted, so `@parcel/watcher` (a dep of `@tailwindcss/cli`) was skipped and `pnpm install` exited **1** with `ERR_PNPM_IGNORED_BUILDS`. That would break CI and Docker builds.
**Solution/Workaround:** Added `allowBuilds: {"@parcel/watcher": false}` to `pnpm-workspace.yaml`. `false` is correct — the prebuilt platform package (`@parcel/watcher-darwin-arm64`) already provides the native binding, so the node-gyp build is unnecessary; watch mode verified working. Note `onlyBuiltDependencies` is deprecated as of pnpm v10.26.0 and is silently ignored.
**Preference:** Set `allowBuilds` explicitly per dependency rather than `dangerouslyAllowAllBuilds`.

### Killing a pnpm-wrapped watcher orphaned the node process
**Area:** web/dev.sh
**Obstacle:** `pnpm run` spawns node as a child, so `$!` captured pnpm's PID rather than the Tailwind process. The `trap "kill $TW_PID"` cleanup killed the wrapper and left the node watcher running, accumulating orphans across dev-server restarts.
**Solution/Workaround:** Enable job control with `set -m` before backgrounding so the job becomes a process-group leader, then kill the group: `kill -- -$TW_PID`.
**Preference:** When backgrounding a package-manager wrapper, always kill the process group rather than the wrapper PID.

### Owned repository pagination needs an owner-specific endpoint
**Area:** web/app/clients/forgejo.py, web/app/routers/repositories.py, web/app/main.py
**Obstacle:** Forgejo's `/user/repos` handler does not read `type=owner`; filtering accessible repositories after pagination can produce sparse pages and misleading totals.
**Solution/Workaround:** Use authenticated `/users/{username}/repos` for owned listings and preserve `x-total-count`. Dashboard and JSON listings consume the returned page without filtering it again.
**Preference:** Filter upstream before paginating; keep the JSON list response shape unchanged. User approved removing redundant consumer-side owner checks because silently dropping results could make page contents disagree with pagination metadata.

### Repository failures must not replace the dashboard
**Area:** web/app/main.py, web/app/templates/dashboard.html
**Obstacle:** Fetch failures and token/identity dependencies could abort the whole dashboard, including its no-PAT state.
**Solution/Workaround:** Resolve repository credentials and identity only when a PAT exists, inside the dashboard's repository error boundary. Render expected 403/502/503 failures inline and hide pagination on error; leave authentication outside that boundary. Use one dashboard page-size constant.
**Preference:** Keep the dashboard usable without masking unexpected application errors.

### Declarative base lint error remains deferred
**Area:** web/app/database.py
**Obstacle:** Existing `Base.type_annotation_map` triggers Ruff RUF012 for an unannotated mutable class attribute.
**Solution/Workaround:** Deferred outside the repository-table cleanup. Annotate the mapping with `ClassVar` when addressing this lint issue.
**Preference:** Do not mix unrelated database cleanup into repository UI changes.

### Link creation must not resolve the branch again
**Area:** web/app/routers/links.py, web/app/clients/forgejo.py
**Obstacle:** A branch can move after preview, and a stored PAT can belong to a different Forgejo account.
**Solution/Workaround:** Match the PAT user ID to the linked identity and repository owner, verify the exact selected SHA, and save only the link token hash. Use a session-bound CSRF token on the browser form; the JSON endpoint only accepts `application/json`.
**Preference:** Keep the picker preview-only and the public viewer separate. The viewer will need to avoid logging raw share tokens.

### Replacing the picker body loses the selected options
**Area:** web/app/templates/dashboard.html, web/app/templates/snapshot_picker.html
**Obstacle:** Swapping review into the picker body removes the loaded repository, branch, and commit controls, so going back would need to reload them.
**Solution/Workaround:** Swap review into a separate dialog region and keep the picker hidden until Back. On successful creation, swap the Share links table out of band before closing the dialog.
**Preference:** Preserve selections without refetching, and show the raw share URL only in the creation response.

### Offline uv lock refresh changed unrelated entries
**Area:** web/uv.lock
**Obstacle:** The local uv 0.10.7 offline refresh downgraded certifi and rewrote the lockfile revision while removing the unused email extra.
**Solution/Workaround:** Retained the original certifi entry and lockfile revision, kept only the email dependency removals, and verified with `uv lock --check`.
**Preference:** Check lockfile diffs for unrelated changes after an offline refresh.

### Table divider utility has no matching theme token
**Area:** web/app/templates/dashboard.html, web/app/static/css/input.css
**Obstacle:** Both dashboard tables use `divide-border-subtle`, but no `--color-border-subtle` token exists. The repository table copied the existing share-links table styling.
**Solution/Workaround:** Replaced `divide-border-subtle` with the existing semantic `divide-border` utility in both dashboard tables, as approved by the user.
**Preference:** Reuse the existing border token rather than adding an appearance-specific token.

### Automated tests deferred while learning the feature
**Area:** web/tests/
**Obstacle:** The user wants to understand how tests work before adding them to this feature.
**Solution/Workaround:** Removed the newly added repository tests at the user's request. Defer adding automated tests until the user is ready; use manual verification in the meantime.
**Preference:** Explain testing before introducing test files; do not add them yet.

### Forgejo page-size caps can hide remaining repositories
**Area:** web/app/clients/forgejo.py, web/app/main.py
**Obstacle:** Calculating the next page from the requested limit stops pagination early when Forgejo's configured page-size cap is lower.
**Solution/Workaround:** Preserve the `next` relation from Forgejo's `Link` header as `RepoPage.has_next_page` and use it directly on the dashboard.
**Preference:** Use upstream pagination links rather than assuming the requested page size was honored.

### Picker listing endpoints omit pagination metadata
**Area:** web/app/routers/repositories.py, web/app/templates/snapshot_picker.html
**Obstacle:** Branch and commit client helpers return plain lists; a short page cannot prove there are no further results because Forgejo may cap page sizes.
**Solution/Workaround:** The picker-specific HTML route follows repository pagination metadata and walks branch pages until empty. Commit requests stop at an empty page or 30 recent commits. JSON listing responses are unchanged.
**Preference:** Paginate automatically without guessing from page length or changing existing API consumers.

### Branch refs need URL query encoding
**Area:** web/app/clients/forgejo.py
**Obstacle:** Interpolating a branch ref into the Forgejo commits query can corrupt names containing characters such as `&` or `#`.
**Solution/Workaround:** Build query strings with `httpx.QueryParams` and quote owner and repository path components.
**Preference:** Encode URL components at the HTTP client boundary.

### Duplicate element IDs silently broke the snapshot picker
**Area:** web/app/templates/dashboard.html, web/app/static/js/snapshot-picker.js
**Obstacle:** The selected-snapshot summary cells reused `snapshot-branch` and `snapshot-commit`, colliding with the picker's `<select>` IDs. `getElementById` returned the hidden summary cell, so `closest(".picker-step")` was `null` and the click handler threw before `showModal()` — the dialog never opened and no visible error appeared.
**Solution/Workaround:** Prefix summary IDs with `snapshot-selected-` and check the rendered template for duplicate IDs.
**Preference:** Keep picker control IDs and display IDs distinct; treat a dialog that fails to open as a JavaScript error first and check the console.

### Appending picker options can change the selected value
**Area:** web/app/templates/snapshot_picker.html
**Obstacle:** A temporary `<select>` wrapper auto-selects its first option before HTMX moves it into the live select, overriding the user's choice.
**Solution/Workaround:** The old paginated UI appended through an inert `<template>` with a neutral wrapper. The current picker renders complete option sets and no longer appends options.
**Preference:** Avoid swapping from a temporary `<select>` when appending to a live one.

### Cached snapshot script broke the new dialog markup
**Area:** web/app/templates/dashboard.html, web/app/static/js/snapshot-picker.js
**Obstacle:** During the HTMX migration, the browser could reuse the old picker script against the new HTML and fail before opening the dialog.
**Solution/Workaround:** The script URL was versioned during the migration. The current picker uses native dialog commands and no longer includes a custom script.
**Preference:** Keep the HTML and its script in sync without requiring users to hard-refresh.

### Forgejo commit listing has no message search
**Area:** web/app/routers/repositories.py, web/app/templates/snapshot_picker.html
**Obstacle:** Filtering just the first page misses commits; scanning an entire branch on each search can slow large repositories.
**Solution/Workaround:** The picker previously filtered up to 100 commits by message or SHA prefix. At the user's request, it now only lists up to 30 recent commits in the dropdown.
**Preference:** Keep the picker dropdown-only; don't scan the entire commit history.

### Snapshot picker changes shifted the modal frame
**Area:** web/app/static/css/input.css, web/app/templates/dashboard.html
**Obstacle:** The dialog only had a maximum height, HTMX loading removed fields from layout, and locking root overflow could remove the page scrollbar.
**Solution/Workaround:** Use a viewport-capped fixed dialog size, a scrolling body with a stable scrollbar gutter, and a grid overlay for loading. Contain scroll chaining on the dialog and its backdrop rather than changing root overflow.
**Preference:** Keep the shell and field space stable without JavaScript.

### djLint reports empty native selectedcontent as an error
**Area:** web/app/templates/snapshot_picker.html
**Obstacle:** djLint H020 flags the empty element even though the browser fills it from the selected option.
**Solution/Workaround:** Suppress H020 in the picker fragment and leave its native select markup intact.
**Preference:** Keep customizable-select styling behind feature queries, with the native picker as the fallback.

### Forgejo owned repository listing requires two PAT scopes
**Area:** web/app/clients/forgejo.py, web/app/templates/settings.html
**Obstacle:** Forgejo's `/users/{username}/repos` requires `read:user` and `read:repository`; a PAT with only `read:repository` cannot populate the dashboard or picker.
**Solution/Workaround:** Name both scopes in setup guidance and the client error for a rejected token.
**Preference:** Keep the owner-specific listing and its pagination metadata.

### Unqualified branch names can resolve to a tag
**Area:** web/app/routers/repositories.py, web/app/clients/forgejo.py
**Obstacle:** Forgejo's commits listing accepts a general Git ref; a tag and branch can have the same name.
**Solution/Workaround:** Resolve the exact branch with Forgejo's branch endpoint once, then use its tip SHA for every commit page in the picker.
**Preference:** Leave the JSON commits endpoint's branch/tag/SHA contract unchanged.

### Malformed Forgejo payloads bypassed inline errors
**Area:** web/app/clients/forgejo.py
**Obstacle:** Non-JSON responses or invalid JSON shapes raised outside the dashboard/picker's HTTP error boundary. Pydantic v2 also lets a validator's `TypeError` escape validation.
**Solution/Workaround:** Validate expected JSON shapes in the client, use `ValueError` for field validation, and return a sanitized 502 for malformed data.
**Preference:** Keep the dashboard and picker usable without displaying upstream response content.

### Failed picker requests can reveal stale selections
**Area:** web/app/templates/dashboard.html, web/app/templates/snapshot_picker.html
**Obstacle:** HTMX clears its loading indicator after a failed request without replacing the old branch or commit controls.
**Solution/Workaround:** Mark the dependent fragment `inert` before sending a request and replace its outer element only when a response swaps. Show an inline error if the old fragment remains after loading.
**Preference:** Don't allow a stale selection to submit; preserve the dialog's layout during loading and failure.

### Review-step failures bubbled past the review listener
**Area:** web/app/templates/dashboard.html
**Obstacle:** HTMX fires request events on the element that sent the request, not on `hx-target`. The Next form lives in the picker body, so a listener on `#snapshot-picker-review` never saw a failed review load, and the dialog showed no error.
**Solution/Workaround:** Listen for `htmx:responseError` and `htmx:sendError` on the dialog and filter by `detail.target`. Show the create form's error if present, otherwise the separate review-load error.
**Preference:** Filter dialog-level listeners by target rather than attaching listeners to swap targets.

### JSON link creation bypassed the expiry options
**Area:** web/app/routers/links.py
**Obstacle:** The dashboard form only offers 1, 7, or 30 days, but `POST /links/` accepted any future `expires_at`, up to year 9999. An extreme offset such as `9999-12-31T23:59:59-14:00` also passed validation and crashed with `OverflowError` when saved.
**Solution/Workaround:** `LINK_LIFETIME_DAYS` in `app/models/grant.py` defines the offered lifetimes. The form validates against it and renders its options from it, and `_create_public_link` rejects expirations beyond its maximum, before any UTC conversion.
**Preference:** Enforce link policy in the shared creation function so every entry point gets it.

### Share-link no-JavaScript fallback was unreachable
**Area:** web/app/routers/links.py, web/app/templates/share_link.html, web/app/templates/share_links.html
**Obstacle:** `POST /links/create` rendered full pages for non-HTMX requests. The picker loads every step through HTMX, so the review form can't be reached without JavaScript. That fallback had no double-submit guard and no copy handler (flagged by CodeRabbit on #31).
**Solution/Workaround:** Removed the full-page branches. The route rejects non-HTMX requests with 400, and both templates are fragments only. API clients use `POST /links/`.
**Preference:** Don't add no-JS fallbacks to steps that only HTMX can reach.

### Primary buttons borrowed the danger red
**Area:** web/app/static/css/input.css, web/app/templates/error.html
**Obstacle:** `.btn-primary` and `.btn-borderless` used `bg-danger`, so "Create link" and the Revoked badge carried the same signal. White on dark `#d93f2d` was 4.47:1, and the dark Revoked badge was 4.3:1. Both are below WCAG AA.
**Solution/Workaround:** Added `--color-brand` (the logo's `#c62030`, white text 5.75:1) with a hover shade, and pointed primary buttons at it. Danger stays for errors and revocation, with explicit `--color-danger-muted` surfaces and lighter `--color-danger-foreground` (dark 5.5:1, light 4.9:1).
**Preference:** Brand red owns actions; danger red means error or revoked. Use explicit hex for muted surfaces instead of translucent overlays, so contrast doesn't depend on what's underneath.
