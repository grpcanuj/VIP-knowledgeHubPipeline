#!/usr/bin/env bash
# Usage: sudo bash deploy/setup_vm.sh <runner-user> [docs-dir]
# One-time VM preparation: directories, nginx config, prerequisite checks. Idempotent.
set -euo pipefail

RUNNER_USER="${1:?usage: sudo bash deploy/setup_vm.sh <runner-user> [docs-dir]}"
DOCS_DIR="${2:-/srv/knowledge-hub/docs}"
BASE="/var/www/knowledge-hub"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[ "$(id -u)" -eq 0 ] || { echo "Run with sudo." >&2; exit 1; }
id "$RUNNER_USER" >/dev/null 2>&1 || { echo "User not found: $RUNNER_USER" >&2; exit 1; }

missing=0
for cmd in git curl nginx python3 node npm; do
  command -v "$cmd" >/dev/null || { echo "Missing: $cmd" >&2; missing=1; }
done
python3 -c "import venv, ensurepip" 2>/dev/null || { echo "Missing: python3-venv" >&2; missing=1; }
if command -v node >/dev/null; then
  node_major="$(node -p 'process.versions.node.split(".")[0]')"
  [ "$node_major" -ge 22 ] || { echo "Node 22+ required, found $(node --version)" >&2; missing=1; }
fi
[ "$missing" -eq 0 ] || { echo "Install the missing prerequisites and re-run." >&2; exit 1; }

mkdir -p "$BASE/dev" "$BASE/uat" "$DOCS_DIR"
chown -R "$RUNNER_USER": "$BASE"
chown "$RUNNER_USER": "$DOCS_DIR"

mkdir -p /etc/nginx/snippets
install -m 644 "$HERE/nginx/knowledge-hub-common.conf" /etc/nginx/snippets/knowledge-hub-common.conf
install -m 644 "$HERE/nginx/knowledge-hub.conf" /etc/nginx/conf.d/knowledge-hub.conf

nginx -t
systemctl enable --now nginx
systemctl reload nginx

echo "VM ready. Deploy base: $BASE  Docs: $DOCS_DIR  Ports: 8080 (UAT), 8081 (Dev)"
echo "Open ports 8080 and 8081 in the VM firewall / network security group if users connect remotely."
