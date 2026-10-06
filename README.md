# ShiftTap — independent multi-store attendance

ShiftTap is a working, portable Flask application with its own email/password authentication and a persistent SQLite database. There are **no ChatGPT APIs, sign-in flows, Sites hosting bindings, or builder runtime dependencies**. It can operate after cancellation of a ChatGPT or website-builder subscription because you deploy it under your own hosting account.

**Release status:** deployment candidate, not certified production-ready. Automated tests pass locally. A live deployment, real SMTP delivery, visual mobile/desktop verification and physical NFC testing are still required on infrastructure you control. Do not use the earlier ChatGPT-hosted ShiftTap URL as this application's production URL; it is a different application and database.

## What is included

- Owner, assigned-store manager and staff roles; server-side permissions.
- Protected console-only owner bootstrap. No public sign-up or first-visitor administrator.
- Invitation-based email activation, password reset, password hashing and revocable server-side sessions.
- Optional authenticator MFA with single-use recovery codes.
- Store editing, archival and revocable NFC URLs; printable SVG QR signs.
- Multi-store staff assignments and immediate account deactivation.
- Server-timestamped clock-in/out, paid/unpaid breaks, validated action order and idempotent retries.
- Database transactions, unique open shifts and overlap/break validation triggers.
- UTC storage, store timezones, overnight shifts and daylight-saving-aware elapsed hours.
- Daily and Monday-to-current-time weekly dashboards, provisional open shifts and long-shift flags.
- Manager corrections with optimistic concurrency and an immutable audit trail; requests and approvals.
- Full-range CSV exports, formula-injection protection and exact seconds (no payroll calculation).
- Optional per-store GPS checks and a manager-reviewed exception process.
- Encrypted scheduled backups, retention settings and restore/export commands.
- Responsive green-and-white screens with no fabricated production data.

## Architecture and operational limits

The supplied deployment is **one Linux server with local persistent storage**. Caddy terminates HTTPS; Gunicorn serves the application; SQLite WAL transactions coordinate the web workers and one maintenance process. SQLite is suitable for this small-store deployment, but this is not a horizontally scaled or highly available cluster. Do not run replicas with separate SQLite copies, put the database on a network filesystem, or use an ephemeral/serverless filesystem. Use a PostgreSQL adaptation before multi-host scaling.

Hosting includes database storage: there is no separate database vendor or authentication subscription. You must maintain the server, security updates, disk space, backups and email delivery. A server outage stops clocking; the interface does not invent successful offline punches.

Audit immutability is enforced through SQLite triggers for application writes. An administrator with direct server/database access can alter the database. External immutable backups or a separate audit service are needed for protection against a malicious infrastructure administrator.

## Accounts and costs

Required accounts are your server provider, domain registrar/DNS provider, an SMTP provider, and an off-server backup destination. Choose an Australian hosting region if that suits your data needs; region availability and privacy obligations must be checked for your circumstances.

Indicative service pricing checked 7 October 2026:

| Item | Example | Cost basis |
| --- | --- | --- |
| Server | DigitalOcean Basic, 2 GiB / 1 vCPU / 50 GiB | US$12/month listed base price; use as a starting size, then monitor |
| Database and authentication | Included app + SQLite on that server | No separate service subscription |
| Transactional email | Resend SMTP, or an SMTP provider you already own | Resend lists a free tier of 3,000 emails/month, limited to 100/day, or Pro at US$20/month |
| Domain | An existing domain/subdomain | Registrar-specific annual renewal |
| Off-server backup storage | Your own S3-compatible storage or separate server | Provider-specific usage charges |

These examples are not guarantees of capacity or total price. Taxes, exchange rates, bandwidth/storage overages, backup charges and operational support can add costs. Sources: https://www.digitalocean.com/pricing/droplets and https://resend.com/pricing. No paid account or service has been created by this package.

## Temporary free URL option

The requested owner email is **adib_haque@hotmail.com**. `render.yaml` and `docs/RENDER_SETUP.md` provide a customer-owned Render deployment with a free `onrender.com` address, paid persistent hosting, and no ChatGPT dependency. The actual hostname is assigned at deployment and has not been reserved. Use that guide if you do not yet own a domain; the Docker/VPS instructions below are the alternative.

## Production setup checklist

### 1. Create your hosting accounts

Provision a supported Linux server with Docker Engine and the Docker Compose plugin. Start with at least 2 GiB memory. Keep the server clock synchronised with NTP. Use SSH keys and keep server/provider account MFA enabled. Keep the infrastructure account in your name.

Upload this complete project directory to the server, for example `/opt/shifttap`. Keep a private Git repository under your account if desired. Do not publish `.env`, production databases or backup keys.

Install Docker using the current official instructions for your server OS: https://docs.docker.com/engine/install/.

### 2. Configure domain, secrets and email

Point an A record for your chosen hostname (for example `clock.yourbusiness.com`) to the server's public IPv4 address. Only add an AAAA record when IPv6 is correctly routed. Allow ports 80 and 443 to Caddy. Restrict SSH to trusted administration where possible. **Do not expose port 8000 to the internet.**

Copy `.env.example` to `.env`, set `APP_URL` to your actual HTTPS origin without a trailing path, and replace all placeholders.

Generate the application secret and backup encryption key on the server:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
docker compose build
docker compose run --rm --no-deps app python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Save the generated values as `APP_SECRET` and `BACKUP_KEY` in `.env`, and back up both keys separately in your password manager. **Losing APP_SECRET prevents decrypting MFA secrets, queued emails and NFC tags. Losing BACKUP_KEY prevents restoring encrypted backups.** Rotation needs a migration, not simply changing the old value.

For SMTP, verify a sending domain with your provider and configure its required DNS records. Set SMTP host, port, TLS mode, credentials and sender. Resend's documented SMTP example is `smtp.resend.com`, port `465`, mode `ssl`, username `resend`, password your restricted API key. You can use another SMTP provider; the app is not tied to Resend. Source: https://resend.com/changelog/smtp-service.

Keep `.env` readable only by the server operator:

```bash
chmod 600 .env
```

`TRUST_PROXY=true` trusts exactly one forwarding proxy. This is appropriate for the supplied Caddy deployment with no public app port. Turn it off for direct loopback development. If changing proxy topology, review IP/header trust; do not trust arbitrary forwarded IPs.

### 3. Start the services and create the owner

```bash
docker compose up -d --build
docker compose exec app python manage.py migrate
docker compose exec app python manage.py owner --email YOUR_REAL_EMAIL --name "YOUR NAME"
```

Replace the final command's placeholders. It can only be run by someone with console access. It refuses to create a second owner. The owner activation email is queued; the maintenance service sends it, normally within one minute. Use the emailed one-time link to verify your email and choose your password, then sign in.

Caddy obtains/renews the HTTPS certificate when DNS and ports are correct. Verify `https://YOUR_HOSTNAME/health` returns `{"ok":true}` and that the browser shows trusted HTTPS. Caddy reference: https://caddyserver.com/docs/quick-starts/https.

Check service status and maintenance logs without logging passwords or links:

```bash
docker compose ps
docker compose logs --tail 80 maintenance
```

Public sign-up does not exist. Configure owner MFA in Settings and save the recovery codes. Keep MFA enabled on hosting, registrar and email-provider accounts too.

### 4. Add locations and staff

Under Locations add the store name, address and IANA timezone (normally `Australia/Sydney`). Location checks are disabled by default. If enabling them, enter coordinates, radius and maximum permitted GPS accuracy.

Under Team invite staff or managers using their actual email addresses, and select their stores. The employee's invitation links to email activation and password setup. A manager can invite new staff for their own stores; the owner controls existing account details, assignments, roles and deactivation.

Store archival preserves history and is blocked while that store has open shifts. A deactivated employee with an open shift remains visible for review; a manager must verify and correct the missed clock-out. No end time is inferred.

### 5. Program NFC tags and print QR signs

Copy a store's clocking URL from Locations. In NFC Tools choose **Write → Add a record → URL/URI**, paste the complete HTTPS link, then write it to that store's tag. Test before locking a tag against rewriting. Each store needs its own link.

Use Print QR to print the same destination as a sign. Staff tap/scan, sign in, and confirm their clock action. Android/iPhone NFC behaviour varies by handset and device settings; a QR sign is the fallback.

Static tag URLs can be copied. They are not proof of physical presence. Revoke link invalidates old NFC tags and QR signs; program/print the replacement. The URL token is a revocable store locator, not an employee credential.

A stronger secure-tag adapter must validate cryptographic tag messages server-side using separately held keys. This release does not provide cryptographic tag verification or claim clone resistance.

### 6. Verify the full live workflow before rollout

Complete `docs/ACCEPTANCE_CHECKLIST.md` with a separate owner and staff account on desktop and on actual iPhone/Android devices. Verify invitation and reset email delivery, MFA, permissions, NFC/QR opening, every break action, CSV output, corrections, denied-location exceptions and a backup restore.

The recorded clock timestamp is the server confirmation timestamp, not the exact physical NFC tap time. Geolocation is requested only when an action requires it. GPS uncertainty is validated, but phone location can still be spoofed.

Keep a manual attendance process until live verification passes. This system records hours; it does not calculate wages, guarantee payroll correctness or claim legal compliance.

### 7. Back up, copy off-server and restore

The maintenance service creates an encrypted consistent SQLite backup at least every 24 hours in the `backups` volume. Its default local retention is 30 days. If the SMTP queue is large or the service is offline, the schedule may be delayed. Monitor service logs and last-backup time.

Force a backup and list files:

```bash
docker compose run --rm --no-deps maintenance python manage.py backup --destination /backups
docker compose run --rm --no-deps maintenance python -c "from pathlib import Path; print('\n'.join(str(p) for p in Path('/backups').glob('*.sqlite.enc')))"
```

A backup on the same server is not protection against server loss. Configure `scripts/offsite-backup.sh` with rclone and a destination under your account, then schedule it with the included cron example. Confirm encrypted files actually arrive and test recovery on a separate server. Keep the encryption keys outside the server. Configure remote lifecycle/retention independently; local deletion does not delete remote backups.

To restore, first save a current backup and download the selected encrypted backup into the backups volume. Stop both writers before restoration:

```bash
docker compose stop app maintenance
docker compose run --rm --no-deps maintenance python manage.py restore /backups/SELECTED_BACKUP.sqlite.enc --confirm STOPPED-AND-BACKED-UP
docker compose up -d
```

Use the real backup filename. The restore command decrypts and checks SQLite integrity, retains a `.pre-restore` database and invalidates restored sessions, reset tokens and unsent auth emails. Staff must sign in again. Revoke/regenerate store links if recovering from a compromised server. Review `docs/OPERATIONS.md` for restoring onto a new host and full-data export.

## Local development

Linux/macOS or Linux through WSL is required for the filesystem migration lock. Production is Linux Docker. The development server is for loopback work only, never public deployment.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export APP_URL=http://localhost:8000
export COOKIE_SECURE=false
export TRUST_PROXY=false
export DB_PATH=data/local.sqlite
export APP_SECRET=YOUR_LOCALLY_GENERATED_64_CHARACTER_SECRET
export ALLOW_LOCAL_OWNER=yes
python manage.py owner-local --email you@example.com --name "Local owner"
python -m flask --app 'shifttap:create_app()' run --host 127.0.0.1 --port 8000
```

The local-only owner command prompts for a password and bypasses email verification only on a loopback origin with the explicit development flag. Never carry that development database into production. For end-to-end local email tests, configure a test SMTP provider with TLS.

Run checks:

```bash
python -m unittest discover -s tests -v
node --check public/app.js
```

The Node command is only a development syntax check; Node is not a production dependency. Tests use separate temporary databases and do not send email to real staff.

## Files

- `shifttap/app.py`: routes, authentication, permissions and configuration.
- `shifttap/attendance.py`: clocking, corrections and timezone-aware totals.
- `shifttap/security.py`: password hashing, token hashing, MFA and GPS validation.
- `shifttap/db.py`, `migrations/`: persistent database and ordered migrations.
- `public/`: complete responsive frontend; no externally loaded fonts/scripts.
- `maintenance.py`, `manage.py`: email queue, retention, backup and administration.
- `Dockerfile`, `compose.yaml`, `Caddyfile`: self-owned HTTPS deployment.
- `tests/`: automated API/database verification.
- `docs/`: environment settings, operations, acceptance and known verification limits.

## What still needs your credentials or infrastructure

A server in your account, SSH access, your chosen domain's DNS, working SMTP credentials and an off-server backup account. None are supplied here. This package has not purchased services, changed DNS, sent staff invitations or moved data from the previous ChatGPT-hosted site. Data migration between the two applications must be planned separately if you have started using the earlier site.
