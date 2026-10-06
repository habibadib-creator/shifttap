# Environment variables

The production deployment loads `.env` into the containers. Never publish that file. `.env.example` contains only placeholders.

| Variable | Required | Purpose |
| --- | --- | --- |
| APP_URL | Yes on VPS; optional on Render | Canonical origin, such as https://clock.example.com. No path, credentials, query or fragment. Used for origin validation and emailed links. On Render, defaults to RENDER_EXTERNAL_URL when unset. |
| APP_SECRET | Yes | At least 32 random characters; generate 64 hex characters. Encrypts MFA secrets, store URL tokens and queued emails. Preserve on restore. |
| BACKUP_KEY | Yes for backups | A Fernet encryption key generated with cryptography. Preserve separately for restore. |
| DB_PATH | Yes in Docker | `/data/shifttap.sqlite`; mounted local persistent storage. |
| BACKUP_DIR | Yes in Docker | `/backups`; encrypted backup volume. |
| COOKIE_SECURE | Yes | `true` in HTTPS production. Only use `false` on loopback development. |
| TRUST_PROXY | Deployment-specific | `true` for the supplied single Caddy proxy, otherwise `false`. The app must not be exposed directly when trusting proxy headers. |
| SMTP_HOST | Yes for production accounts | Verified outbound SMTP service. Invitations are blocked without it. |
| SMTP_PORT | Yes | Usually 465 (SSL) or 587 (STARTTLS). |
| SMTP_MODE | Yes | `ssl` or `starttls`; unencrypted SMTP is rejected. |
| SMTP_USERNAME | Provider-dependent | SMTP account username. |
| SMTP_PASSWORD | Provider-dependent | Restricted SMTP password/API key; secret. |
| SMTP_FROM | Yes | Verified sender, such as `ShiftTap <attendance@yourdomain.com>`. |
| ALLOW_LOCAL_OWNER | Development only | `yes` explicitly permits loopback-only password bootstrap. Do not set in production. |

Settings stored in the database: long-shift threshold, attendance retention, GPS event retention and encrypted local backup retention. The Settings screen is owner-only for changes.

Sessions use random opaque HttpOnly cookies; only token hashes are stored server-side. Maximum life is 30 days and idle expiry is seven days. Password reset/deactivation revokes sessions. MFA enrollment revokes the other user sessions. Origin validation and a per-session CSRF token protect JSON writes.

Do not log request bodies, NFC paths, activation/password-reset URLs or authentication cookies. The supplied Gunicorn and Caddy configuration does not enable access logging. Error logs can be reviewed without deliberately recording secrets.

Render-only: `PORT` is supplied by the host; `RENDER_EXTERNAL_URL` supplies the assigned HTTPS origin; `OWNER_EMAIL=adib_haque@hotmail.com` is a bootstrap convenience, not an authentication secret or automatic administrator grant.
