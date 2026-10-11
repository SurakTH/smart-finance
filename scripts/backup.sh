#!/bin/sh
set -eu
umask 077
cd "$(dirname "$0")/.."
mkdir -p backups
backup_path="backups/finance-$(date -u +%Y%m%dT%H%M%SZ).dump"
docker compose exec -T postgres pg_dump -U finance -d finance --format=custom > "$backup_path"
echo "Database backup saved: $backup_path"
echo "Also back up .env securely; ENCRYPTION_KEY is required to decrypt provider credentials."
