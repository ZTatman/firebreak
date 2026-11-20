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
**Area:** cli/src/utils/forgejo-checks.ts, cli/src/commands/config/init.ts, web/app/services/forgejo.py
**Obstacle:** CLI setup and verification accepted remote `http://` Forgejo URLs, allowing the PAT to be sent without transport encryption.
**Solution/Workaround:** Centralize Forgejo URL validation, require HTTPS for non-local endpoints, and allow HTTP only for the documented `forgejo` service and loopback hosts. Validate again inside authenticated checks before constructing requests. The web inspection client follows the same transport rule and disables redirects.
**Preference:** Reject insecure remote transport instead of adding an acknowledgement flag.

### Forgejo identity and branch JSON field names
**Area:** web/app/routers/auth.py, web/app/routers/links.py
**Obstacle:** Forgejo's documented user response exposes `login`, not `username`, and a branch response exposes its immutable SHA at `commit.id`. Looking up the wrong fields prevents sign-in or commit pinning.
**Solution/Workaround:** Parse `login` for OAuth (retaining the old `username` fallback), compare PAT and OAuth user IDs, and validate the SHA from `branch.commit.id`. Require `read:user` plus `read:repository` PAT scopes.
**Preference:** Use immutable IDs for personal ownership; collaborator/admin permissions never authorize sharing.

### JSON inspection and browser error pages
**Area:** web/app/main.py, web/app/middleware.py, web/app/routers/links.py
**Obstacle:** Browser requests normally receive HTML errors or setup redirects; inspection routes need consistent JSON, and default validation errors echo rejected values.
**Solution/Workaround:** Return JSON for `/links/` errors and setup failures, omit validation input values, redact credentials from optional upstream inspection data, and set `Cache-Control: no-store`. Accept only JSON bodies for grant creation.
**Preference:** Keep inspection behind the existing owner session; never persist upstream payloads or return stored token hashes.
