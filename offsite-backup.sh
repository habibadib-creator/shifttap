#!/bin/sh
# Requires rclone configured by the server operator. No credentials in this script.
set -eu
: "SHIFTTAP_HOME:?Set SHIFTTAP_HOME to the absolute project path}"
: "SHIFTTAP_REMOTE:?Set SHIFTTAP_REMOTE to your rclone remote:path}"
cd "$SHIFTTAP_HOME"
command -v rclone >/dev/null
umask 077
backup_tmp=$(mktemp -d)
trap 'rm -rf "$backup_tmp"' EXIT HUP INT TERM
docker compose run --rm --no-deps maintenance python manage.py backup --destination /backups
docker compose run --rm --no-deps -T maintenance tar -C /backups -cf - . | tar -C "$backup_tmp" -xf -
rclone copy "$backup_tmp" "$SHIFTTAP_REMOTE" --include '*.sqlite.enc' --include '*.sha256'
