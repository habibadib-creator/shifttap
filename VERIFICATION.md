# Build verification

Thirty-eight automated unittest checks passed in the authoring environment on 6 October 2026. They exercise actual Flask routes and a migrated temporary SQLite database, including independent owner/staff sessions. No production data or real invitations are used.

Covered: protected owner bootstrap surface; cookies/security headers; origin/CSRF; staff/manager/store boundaries; identity selection protection; deactivation/session invalidation; retry replay and mismatched keys; concurrent punches and simultaneous same-key retries; paid/unpaid breaks and clock-out closure; invalid sequences; database overlap constraints and immutable audit; correction versions/history; location missing/invalid/uncertain readings; exception requests not creating punches; URL rotation/archival; single-use activation; overnight/DST/day clipping; full CSV beyond pagination/formula protection; MFA/recovery/TOTP replay; approval blocking; encrypted backup roundtrip/integrity; HTML/static routes and QR generation.

Additional checks cover MFA enrollment, session expiry, correction version changes after breaks, invalid identifiers, login rate limits, parallel migration startup, scheduled maintenance backups, and manual-shift overlap/approval.

Also passed: Python compilation, frontend JavaScript syntax check, shell syntax check for the off-server backup script.

Limits: no Docker daemon, live deployment, real SMTP, DNS, off-server storage, actual NFC devices or installed browser binary were available. Browser download failed. Do not interpret API/static-route checks as visual browser verification. Complete ACCEPTANCE_CHECKLIST.md on your own hosting before production rollout.

Browserless frontend integration also passed against the actual Flask HTTP app with separate temporary owner and staff accounts. It verifies all manager views, escaped store names, store creation, staff invitation, manual shift with a break, correction, history, approval, and staff login/clock-in/break/resume/clock-out. It does not verify visual layout or actual mobile browser behaviour.

To reproduce: install development-only jsdom@26.1.0 in an isolated folder, then run `NODE_PATH=/ABSOLUTE/FOLDER/node_modules node tests/frontend.cjs`. It starts a disposable loopback fixture on port 8901 and sends no real emails.
