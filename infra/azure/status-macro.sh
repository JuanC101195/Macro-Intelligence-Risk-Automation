#!/usr/bin/env bash
# Status of Crucix + recorder on the Azure VM (read-only).
#   az vm run-command invoke -g rg-itp-macro -n vm-itp-macro --command-id RunShellScript \
#     --scripts @infra/azure/status-macro.sh --query "value[0].message" -o tsv
cd /opt/itp/app/infra/docker || exit 1
COMPOSE="docker compose -f docker-compose.macro.yml"

echo "--- containers ---"
$COMPOSE ps --format '{{.Service}} {{.State}} {{.Status}}'
echo "--- recorder log (last 4) ---"
$COMPOSE logs --tail 4 --no-log-prefix recorder | cut -c1-160
echo "--- snapshots ---"
python3 - <<'PY'
import glob, json
files = sorted(glob.glob("data/macro_snapshots/*.jsonl"))
lines = [json.loads(l) for f in files for l in open(f) if l.strip()]
print(f"files={len(files)} snapshots={len(lines)}")
for x in lines[-5:]:
    c = x["context"]
    print(x["recorded_at"][:19], c["risk_regime"], "vix=", c["vix"], "stale=", c["data_stale"])
PY
echo "--- host ---"
free -m | sed -n 2p
df -h / | tail -1
