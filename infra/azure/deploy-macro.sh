#!/usr/bin/env bash
# Deploy/update Crucix + macro recorder on the Azure VM (runs as root via run-command).
#   az vm run-command invoke -g rg-itp-macro -n vm-itp-macro --command-id RunShellScript \
#     --scripts @infra/azure/deploy-macro.sh --parameters <FRED_API_KEY> [branch]
# The key is written to crucix.env (mode 600) and never echoed.
set -euo pipefail

FRED_KEY="${1:?FRED_API_KEY required}"
BRANCH="${2:-main}"
REPO="https://github.com/JuanC101195/Macro-Intelligence-Risk-Automation.git"
APP=/opt/itp/app
# Repo is owned by azureuser but this script runs as root.
export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=safe.directory GIT_CONFIG_VALUE_0="$APP"

mkdir -p /opt/itp
if [[ ! -d "$APP/.git" ]]; then
  git clone -q -b "$BRANCH" "$REPO" "$APP"
else
  git -C "$APP" fetch -q origin
  git -C "$APP" checkout -q "$BRANCH"
  git -C "$APP" pull -q --ff-only origin "$BRANCH"
fi

cd "$APP/infra/docker"
( umask 077; printf 'FRED_API_KEY=%s\n' "$FRED_KEY" > crucix.env )
mkdir -p data/macro_snapshots
chown -R azureuser:azureuser /opt/itp

echo "commit: $(git -C "$APP" log -1 --format='%h %s')"
if ! docker compose -f docker-compose.macro.yml up -d --build > /tmp/compose-up.log 2>&1; then
  tail -40 /tmp/compose-up.log
  exit 1
fi
tail -3 /tmp/compose-up.log
docker compose -f docker-compose.macro.yml ps --format 'table {{.Service}}\t{{.State}}\t{{.Status}}'
