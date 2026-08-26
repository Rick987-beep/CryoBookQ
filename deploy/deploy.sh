#!/usr/bin/env bash
# CryoBookQ deploy — NEVER run against prod without explicit approval.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

DRY_RUN=0
MODE="deploy"
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --setup) MODE=setup ;;
    --status) MODE=status ;;
    --logs) MODE=logs ;;
    --help|-h) MODE=help ;;
  esac
done

CONF="${BOOKQ_SERVERS_TOML:-$ROOT/servers.toml}"
if [[ ! -f "$CONF" ]]; then
  CONF="$ROOT/servers.toml.example"
fi

REMOTE_SSH="$(python3 -c "
import pathlib
p=pathlib.Path('$CONF')
section=None; vals={}
for line in p.read_text().splitlines():
    line=line.strip()
    if line.startswith('[') and line.endswith(']'):
        section=line[1:-1].strip(); continue
    if section=='apps' and '=' in line and not line.startswith('#'):
        k,v=line.split('=',1); vals[k.strip()]=v.strip().strip('\"').strip(\"'\")
print(vals.get('user','root')+'@'+vals.get('host','apps.aureas.xyz'))
")"
REMOTE_PATH="$(python3 -c "
import pathlib
p=pathlib.Path('$CONF')
section=None; vals={}
for line in p.read_text().splitlines():
    line=line.strip()
    if line.startswith('[') and line.endswith(']'):
        section=line[1:-1].strip(); continue
    if section=='apps' and '=' in line and not line.startswith('#'):
        k,v=line.split('=',1); vals[k.strip()]=v.strip().strip('\"').strip(\"'\")
print(vals.get('path','/apps/cryobookq'))
")"

echo "target=$REMOTE_SSH path=$REMOTE_PATH mode=$MODE dry_run=$DRY_RUN"

case "$MODE" in
  help)
    echo "Usage: $0 [--dry-run] [--setup|--status|--logs]"
    echo "Live deploy requires BOOKQ_ALLOW_DEPLOY=1 after explicit approval."
    exit 0
    ;;
  setup)
    echo "On server after approval:"
    echo "  mkdir -p $REMOTE_PATH/{data,logs}"
    echo "  python3.12 -m venv $REMOTE_PATH/.venv && $REMOTE_PATH/.venv/bin/pip install -e '.[hub]'"
    echo "  install deploy/cryobookq.service; merge deploy/nginx-bookq.conf; create .env mode 600"
    ;;
  status)
    ssh ${SSH_KEY:+-i "$SSH_KEY"} -o BatchMode=yes "$REMOTE_SSH" "systemctl is-active cryobookq"
    ;;
  logs)
    ssh ${SSH_KEY:+-i "$SSH_KEY"} -o BatchMode=yes "$REMOTE_SSH" "journalctl -u cryobookq -n 100 --no-pager"
    ;;
  deploy)
    echo "rsync excludes: .env data/ .venv .git tmp/"
    echo "rsync target: ${REMOTE_SSH}:${REMOTE_PATH}/"
    if [[ "$DRY_RUN" == "1" ]]; then
      echo "[dry-run] skipping rsync/ssh; live deploy still requires BOOKQ_ALLOW_DEPLOY=1"
      exit 0
    fi
    if [[ "${BOOKQ_ALLOW_DEPLOY:-}" != "1" ]]; then
      echo "Refusing live deploy without BOOKQ_ALLOW_DEPLOY=1 (explicit operator approval)."
      echo "Use --dry-run to preview."
      exit 2
    fi
    RSYNC_SSH="ssh -o BatchMode=yes"
    if [[ -n "${SSH_KEY:-}" ]]; then
      RSYNC_SSH="$RSYNC_SSH -i $SSH_KEY"
    fi
    rsync -az --delete \
      --exclude '.env' --exclude 'data/' --exclude '.venv' --exclude '.git' \
      --exclude 'tmp/' --exclude '__pycache__' --exclude '.pytest_cache' \
      -e "$RSYNC_SSH" \
      ./ "${REMOTE_SSH}:${REMOTE_PATH}/"
    ssh ${SSH_KEY:+-i "$SSH_KEY"} -o BatchMode=yes "$REMOTE_SSH" \
      "cd $REMOTE_PATH && .venv/bin/pip install -e '.[hub]' -q && systemctl restart cryobookq && systemctl is-active cryobookq"
    ;;
esac
