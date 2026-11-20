# Firebreak

> Fight fire with fire. Your code. Your rules.

Firebreak is a companion service for Forgejo that lets repo owners create expiring, revocable, read-only share links for code snapshots.

## System Diagram

This diagram shows how traffic moves through the public internet, the VPS or self-hosted server, the host firewall, the platform router, Firebreak, Forgejo, and Postgres.

[![Firebreak system routing diagram](docs/diagrams/system-routing.svg)](docs/diagrams/system-routing.svg)

Click the diagram to open the full-size SVG.

## Features

### Two Link Types

| Type | Verification | Use Case |
|------|--------------|----------|
| **Private** | Email verification code required | Share with specific individuals |
| **Public** | No verification, time-expired | Job applications, portfolios |

### Security

- Links pinned to immutable `commit_sha` — not moving branches
- Email verification prevents unauthorized access
- Time-expiration and revocation give owners control
- No public repo listing — anti-scraping by design
- Admin access protected upstream (Tailscale, VPN, Cloudflare Access)

### Authentication

| Purpose | Method |
|---------|--------|
| User Identity | Forgejo OAuth |
| Data Access | User's Forgejo PAT |

### Tech Stack

- **Backend**: Python + FastAPI
- **Frontend**: Jinja2 templates + HTMX (no build step)
- **Database**: PostgreSQL

HTMX provides interactivity (filtering, form submissions) with minimal JavaScript. Jinja2 handles server-side rendering for fast page loads.

## Quick Start

### 1. Deploy with Docker Compose

```bash
docker compose up -d
```

### 2. Generate an Encryption Key

Firebreak encrypts OAuth tokens and PATs at rest using a Fernet key. Generate one and add it to your environment before running the setup wizard:

```bash
uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Add the output to your `.env` file (or your deployment platform's environment variables):

```bash
TOKEN_ENCRYPTION_KEY=your-generated-key-here
```

### 3. Run the Setup Wizard

Open `http://localhost:8000` in your browser. On first boot, Firebreak redirects to a setup wizard where you configure:

- **Forgejo instance URL** — where your Forgejo server lives
- **OAuth credentials** — register an OAuth application in Forgejo first (Settings → Applications → Create OAuth2 Application), then paste the Client ID and Client Secret
- **Public base URL** (optional) — your production domain for OAuth redirects

### 4. Sign In and Register Your Token

After setup, sign in with your Forgejo account via OAuth. Register a Personal Access Token (PAT) for the same account with `read:user` and `read:repository` scopes in Settings to enable repository inspection and public grant creation. The code viewer is not implemented yet.

See [Inspect repository and grant JSON](docs/public-link-inspection.md) for the authenticated API workflow and example responses.

### 5. Alternative Deployments

For non-Docker deployments, supply `DATABASE_URL` yourself:

- VPS deployment: Hostinger or another VPS with Dokploy, Traefik, UFW, Firebreak, Forgejo, and a shared Postgres instance that contains separate `forgejo` and `firebreak` databases.
- Self-hosted server deployment: a home server, mini PC, NAS, or other self-hosted Linux machine running Firebreak with Docker, Podman, Docker Compose, Coolify, Caddy, Nginx, or another reverse proxy.

Firebreak should not assume a VPS-only environment. The requirement is an existing Forgejo instance, Firebreak's own database, and a way to route the public and admin hostnames to the Firebreak app.

## Phase 1 Progress

- [x] Project renamed from Embargo to Firebreak
- [x] CLI scaffold (`firebreak config init`)
- [x] Config generation (`.env`)
- [ ] Service foundation (FastAPI + PostgreSQL)
- [x] `firebreak config verify` — verify Forgejo connectivity
- [x] `firebreak config verify --diagnostic` — comprehensive diagnostics
- [x] `firebreak config view` — show current config
- [x] Forgejo OAuth authentication
- [x] Personal repository ownership verification
- [ ] Private link creation (email-verified)
- [x] Public grant creation (API; pins a commit and records expiration)
- [ ] Public link viewing with expiration/revocation enforcement
- [ ] Web-based code viewer
- [x] User dashboard
- [ ] SMTP configuration UI
- [ ] Access logs

## Resources

- [Forgejo Docs](https://forgejo.org/docs/)
- [API Usage](https://forgejo.org/docs/latest/user/api-usage/)
- [Token Scopes](https://forgejo.org/docs/latest/user/token-scope/)
