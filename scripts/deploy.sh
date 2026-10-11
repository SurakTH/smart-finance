#!/usr/bin/env bash
# Ubuntu host: /opt/smart-finance/.env and registry login must already exist.
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
root=/opt/smart-finance
sha=${1:?commit required}
export BACKEND_IMAGE=${2:?backend image required}
export WEB_IMAGE=${3:?web image required}
[[ "$sha" =~ ^[a-f0-9]{40}$ ]] || exit 2
[[ "$PWD" == "$root/releases/$sha" ]] || { echo 'Unexpected release directory'; exit 2; }
[[ -f "$root/.env" ]] || { echo 'Configure server .env first'; exit 2; }
exec 9>"$root/deploy.lock"
flock -n 9 || { echo 'Another deployment is running'; exit 2; }
ln -sfn "$root/.env" .env
mkdir -p "$root/backups"
ln -sfn "$root/backups" backups
export COMPOSE_FILE=compose.yaml:compose.nginx.yaml:compose.release.yaml
# Require explicit production configuration without printing the merged config.
docker compose config -q
python3 - <<'PY'
from pathlib import Path
values={}
for line in Path('.env').read_text().splitlines():
    if '=' in line and not line.lstrip().startswith('#'):
        k,v=line.split('=',1);values[k]=v.strip().strip('\"\'')
if not values.get('APP_ORIGIN','').startswith('https://') or values.get('COOKIE_SECURE')!='true' or values.get('BIND_ADDRESS','127.0.0.1')!='127.0.0.1':
    raise SystemExit('Production requires HTTPS APP_ORIGIN, COOKIE_SECURE=true and loopback gateway')
PY
docker compose pull api worker migrate web proxy
# This script upgrades an initialized server, not first-time provisioning.
sh scripts/backup.sh
# Avoid old workers writing while the migration and version switch run.
docker compose stop worker
if ! docker compose up -d --no-build --wait --wait-timeout 180; then
    echo 'Deployment failed. Backup retained. Inspect before rollback; database migrations are not automatically reversed.'
    exit 1
fi
# HTTP check stays inside the private app network, never prints response bodies.
docker compose exec -T api python -c "import urllib.request; assert urllib.request.urlopen('http://localhost:8000/health',timeout=10).status==200"
docker compose exec -T web node -e "fetch('http://127.0.0.1:3000/').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"
printf '%s\n' "$sha" > "$root/current-commit"
echo 'New release healthy. Existing host Nginx configuration retained.'
