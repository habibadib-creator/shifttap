# Live acceptance checklist — complete before staff rollout

Deployment URL: __________________  Date: __________  Tester: __________

## Ownership and infrastructure

- [ ] Hosting, DNS, SMTP, source repository and backup accounts are owned by the business.
- [ ] No ChatGPT login or subscription is needed to open/sign in to the application.
- [ ] HTTPS is trusted and redirects correctly. Port 8000 is not publicly exposed.
- [ ] App and maintenance services are healthy; no production sample data is installed.
- [ ] Infrastructure accounts have MFA and keys are stored securely outside the server.

## Separate identities and email

- [ ] Protected console bootstrap creates one owner and rejects a second bootstrap.
- [ ] Owner receives activation email, verifies email and sets a password.
- [ ] Owner enrols MFA, signs out/in with an authenticator and saves recovery codes.
- [ ] A staff invitation reaches the staff inbox; a used or expired link fails safely.
- [ ] Password reset succeeds, old sessions are revoked and MFA remains required.
- [ ] Staff cannot become owner/manager through request manipulation.

## Multi-store permissions

- [ ] Create stores A and B, assign manager A to A and staff A to A.
- [ ] Owner sees both stores; manager A cannot read/manage B.
- [ ] Staff A cannot read another employee's records or export payroll data.
- [ ] Staff A cannot clock another identity or use store B's tag.
- [ ] Deactivation revokes an existing staff browser session immediately.
- [ ] Revoking a store link makes its old NFC/QR URL fail.
- [ ] Archival preserves history and rejects archival with open shifts.

## Desktop and actual phones

- [ ] Owner dashboard, store/team forms, timesheets, corrections and QR printing work on desktop.
- [ ] Staff login and clock page work on actual iPhone Safari and Android Chrome.
- [ ] On both phones: NFC/QR opens the correct store and simply opening it creates no punch.
- [ ] Clock In → paid break → resume → unpaid break → Clock Out works.
- [ ] Clock Out during an active break closes it and deducts only unpaid time.
- [ ] Changing the phone's clock does not change the stored timestamp.
- [ ] Concurrent clicks/devices cannot open overlapping shifts.
- [ ] Network loss shows no false success; retry reconciles the original action.
- [ ] Forms, navigation and dialogs remain usable at narrow mobile widths and with keyboard controls.

## Dates, exports and review

- [ ] An overnight shift is displayed correctly across both dates.
- [ ] Sydney DST boundaries produce elapsed hours, not naive clock differences.
- [ ] CSV includes all matching rows beyond page one; exact seconds match expectations.
- [ ] Formula-like employee/store text is neutralised in Excel.
- [ ] Correction keeps original values, records manager/reason and returns approval to pending.
- [ ] A stale correction is rejected after concurrent break/punch changes.
- [ ] A staff correction request must be resolved before approval.
- [ ] Missing clock-outs are flagged; no automatic invented end time appears.

## Location and exceptions

- [ ] Location permission is requested only for a required clock action.
- [ ] Within-radius accurate readings pass; uncertain/outside readings are rejected.
- [ ] Denied permission provides a request path without fabricating a punch.
- [ ] Manager reviews exception and creates/corrects verified attendance separately.
- [ ] Staff understand static tags/GPS are not definitive proof of presence.

## Recovery and operation

- [ ] A scheduled encrypted backup is created and copied off-server.
- [ ] A restored backup on a separate test server passes integrity checks and matches records.
- [ ] Restore invalidates sessions and old password-reset links.
- [ ] Daily monitoring identifies email failure, backup failure and disk exhaustion.
- [ ] Retention settings are reviewed; audit and remote backup retention are understood.
- [ ] A manual fallback exists for outages.

Rollout decision: __________________  Remaining issues: __________________
