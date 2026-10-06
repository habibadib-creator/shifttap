# Operations, restore and limitations

## Daily operation

Keep exactly one maintenance service running. Check `docker compose ps`, maintenance errors, disk space and backup age. Configure infrastructure monitoring under your own account for HTTPS reachability, server health and backup failures. The health endpoint checks the web process, not successful email delivery or off-server backup delivery.

The email queue retries transient failure with exponential delay, for up to ten attempts. Errors remain visible to the server operator through logs and the queue's `last_error`/`attempts` fields. After fixing SMTP, owner-resend creates a fresh email/link. Old activation links expire after 24 hours; password reset links after one hour. An SMTP accepted message does not guarantee inbox delivery. Verify your provider's delivery/bounce logs and sending-domain DNS.

Only encrypted email bodies are stored; successfully sent bodies are cleared. Queue delivery is at least once, so an ambiguous SMTP acknowledgement can produce a duplicate email containing the same one-time link.

## Permission boundaries

Owners manage everything. Managers read staff who share their stores, invite new staff assigned to their own stores, edit store settings, correct/approve assigned-store shifts and review requests. Only owners change roles/assignments of existing staff, deactivate accounts, create/archive stores, rotate tag links or change global settings. Staff see only their own attendance, own requests and assigned stores; they do not receive other employee records or secret store-link lists.

A manager cannot invite a duplicate email to take over an existing account. Email changes require deactivating the old account and issuing a new verified invitation, preserving the old identity and history. There is one owner identity. Owner transfer is not implemented in the UI; perform an audited console migration if needed.

If an active employee loses a store assignment with an open shift, the staff clock page will reject that old store link. A manager must verify and close/correct the old shift. Do not remove assignments casually during a shift. Deactivated employees' open shifts remain for review rather than receiving fabricated end times.

## Attendance and dates

Timestamps are integer Unix seconds. Worked duration uses elapsed seconds, excludes only unpaid breaks and is unaffected by daylight-saving clock jumps. Displayed decimals are convenience values; CSV contains exact seconds.

Date-range filters select any overlapping shift and clip the range total to store-local calendar boundaries. The export includes both complete shift seconds and seconds within the filter, so a cross-midnight shift can appear in consecutive daily exports without double-counting when using the clipped column. Weekly dashboard totals run from local Monday midnight to the current time. Open shifts are always provisional.

Clock actions are transaction-protected and use permanent idempotency records. A network retry with the same key and payload replays the original result; a changed payload with the same key is rejected. Deactivation and sign-in checks apply before retry access too. Browser memory keeps an unconfirmed request until retried, but closing the tab loses that pending request. Reopen the app and inspect current shift state before recording another action.

Corrections require a reason and a current version. Break/resume/punch actions increment the version so a concurrent correction cannot overwrite unseen attendance. Managers edit times with explicit ISO timezone offsets to avoid ambiguous DST times. Manual entries are completed, verified shifts only; no backdated open shift is fabricated from a denied GPS request.

## Retention

Attendance retention defaults to disabled. With a configured period of at least 365 days, maintenance deletes only completed, approved shifts older than the period with no pending correction request. Deleted shifts also lose their break and resolved request rows. Open/unapproved shifts remain. GPS coordinates default to 90-day retention, encrypted local backups to 30 days.

**Immutable audit records are not deleted by the attendance-retention setting.** Original corrected timestamps and reasons can remain there. Accounts, store history, exception requests and idempotency records are also retained. This setting is not a comprehensive personal-data erasure tool. Decide retention for audit/accounts/remote backups with appropriate business requirements before using real employee data; implement a separate authorised offline archive/purge if needed. No legal compliance is asserted.

## Backup and restore

Backups use SQLite's consistent online backup API, then encrypt the snapshot with Fernet authenticated encryption. The local scheduler attempts a backup every 24 hours, with a 60-second maintenance loop. It also writes a SHA-256 checksum for the ciphertext. Keep enough memory/disk for the database snapshot; the encryption step loads the database into memory. This is intended for a small-store database, not an unbounded data warehouse.

Copy backups off-server automatically. `scripts/offsite-backup.sh` makes a fresh backup, copies the backup volume into a private temporary folder, and uses your own rclone destination. Run it at least daily through cron. Configure destination lifecycle rules, credentials and access independently. Losing both the server and on-server volume loses everything unless the remote copy succeeded.

Before restoring, stop app and maintenance. Keep the current backup and image/source version. Restore checks encryption and SQLite integrity, saves a pre-restore database and removes sessions, reset tokens and unsent emails. Never restore while any writer is running.

On a new host: deploy the same project, restore APP_SECRET/BACKUP_KEY from your password manager, stop app/maintenance after creating volumes, copy the encrypted backup into `/backups`, run the restore command from README, update DNS, restart and verify. Retain the secret corresponding to the backup, not a newly generated secret. Validate staff/store/shift totals and regenerate links if compromise is suspected. Migrations are applied on startup under a filesystem lock; append migrations for future changes and never change applied migration SQL.

## Full data export

For a portable JSON data export without passwords, sessions or authentication secrets:

```bash
docker compose exec -T app python manage.py export-data > attendance-export.json
```

Store the resulting employee data securely. This is an export for analysis/migration, not a drop-in restore. Use encrypted database backups for exact restoration. Frontend CSV export applies role/filter permissions and includes all matching shifts, not just the displayed 50-row page.

## Owner recovery

Use a saved MFA recovery code first. If all factors/codes are lost, an authorised infrastructure operator can run:

```bash
docker compose exec app python manage.py owner-recover --email YOUR_OWNER_EMAIL
```

The command prompts for an explicit console confirmation, revokes sessions, resets owner MFA and adds an immutable audit entry. It does not change the owner's password or bypass email ownership. Use the verified email reset flow if needed, and re-enrol MFA afterward. Console access is therefore a privileged trust boundary; protect SSH and provider accounts.

## Updates and rollback

Make a backup before updates. Review new dependencies and migrations, test in staging, then deploy. SQL migrations use SQLite triggers and locking; only one server host with local storage is supported. Rolling back application code after a schema migration requires a compatibility review or restoration of the matching backup. Do not blindly delete volumes to roll back. `docker compose down -v` deletes the production volumes; never use it as a routine restart.

## Items not verified in this build environment

No customer-owned cloud server, real domain, SMTP account or physical NFC tag was available. Docker images were not built here because Docker is unavailable. A browser binary could not be installed, so visual browser QA was not completed. Automatic SMTP delivery and off-server rclone transfer were not run against real accounts. Complete the acceptance checklist on the target server before calling this release production-ready.
