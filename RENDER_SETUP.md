# Temporary free address on your own Render account

Owner email requested: **adib_haque@hotmail.com**.

The app includes `render.yaml` for a customer-owned Render service. Render assigns an `onrender.com` address with managed HTTPS; no purchased domain is needed to start. A custom domain can be attached later. The proposed service label is `shifttap-adib`; the actual hostname is assigned by Render and may have a unique suffix. **No hostname is registered, reserved or live yet.**

The address is free; this is not a promise of free hosting. Persistent disks require a paid service. This blueprint selects the 2 GiB `1c-2g` plan, listed at US$25/month plus a 5 GB disk at US$0.25/GB/month: approximately US$26.25/month before any extra email, backup storage, bandwidth, tax or currency charges. Confirm the price in your Render account before applying. Sources checked 7 October 2026:

- https://render.com/docs/web-services
- https://render.com/docs/disks
- https://render.com/docs/blueprint-spec
- https://render.com/pricing

## Connect and deploy

1. Create/sign in to Render under `adib_haque@hotmail.com`, or another hosting account you own. This email is the intended application-owner login; it is not an account password and grants no existing account access.
2. Put this complete project into a private Git repository you own. Link that repository to Render. Alternatively, connect the Render integration in ChatGPT so supported deployment steps can be completed using your account. Never paste your password into chat.
3. Create a Blueprint using `render.yaml`. Choose/confirm the service name, paid plan and persistent disk. Singapore is the supplied region; change it before provisioning if desired.
4. Supply your verified SMTP host, username, password/API key and sender. The blueprint defaults to port 465 and SSL; change to 587/STARTTLS if that is your provider's requirement. Email services generally require a verified sending domain; using a free website address does not itself verify an email sender. You can use an existing SMTP service/domain you own.
5. Deploy. The app uses `RENDER_EXTERNAL_URL` as its origin automatically if `APP_URL` is unset. Confirm HTTPS and `/health` on the actual assigned address. Keep a single instance; the SQLite disk cannot be shared with another service.
6. In the service's Shell run:

```bash
python manage.py owner --email adib_haque@hotmail.com --name "Adib"
```

The command refuses to create a second owner. It queues an activation email; choose your own password through that email. No preset or shared password is included. Sign in, enable MFA and save the recovery codes.

7. Add stores, invite staff, program the NFC tags and complete `ACCEPTANCE_CHECKLIST.md` on desktop and actual phones.
8. Save the generated APP_SECRET and BACKUP_KEY outside Render. Set up automated off-service copies of encrypted database backups; backups in `/var/data/backups` share the same disk. This package's Docker/rclone cron example is for a VPS; adapt offsite transfer for Render using your own backup agent or an external scheduled SCP/SFTP pull, following Render's supported disk transfer guidance. Do not claim offsite protection until a copy and restore have been verified.

`run_services.py` supervises Gunicorn and maintenance together, so both use the same persistent disk. It shuts down if either child exits, allowing the host to restart the service. No separate Render background worker is configured because it would not have access to this disk.

## Changing to your own domain later

Add/verify the domain in Render, then set `APP_URL=https://YOUR_NEW_HOSTNAME` in the service environment and redeploy. Check login, origin/CSRF protection and emailed links. New store URLs will use the new domain. Keep the old onrender.com address accessible until old tags/QR signs are reprogrammed, and deliberately plan redirects so old NFC links remain usable. Signed-in browser sessions do not transfer across unrelated domains; staff must sign in again.

## Restoring on Render

Stop the web/maintenance processes before an exact database restore. Do not run the restore command while `run_services.py` is writing. Use a controlled maintenance deployment with the persistent disk mounted and no live writers, restore the encrypted snapshot, then restart the standard entrypoint. Test this process in a separate staging service before production rollout. Do not substitute a whole-disk snapshot restore for a verified SQLite backup/restore.

## Still required

Render account connection, a customer-owned Git repository (or supported uploaded image deployment), working SMTP credentials, off-service backup configuration and live acceptance testing. No account, paid service, email or temporary domain was created during preparation of this source package.
