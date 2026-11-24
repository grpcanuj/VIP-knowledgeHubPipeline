#!/usr/bin/env bash
# Usage: deploy.sh <dev|uat> <variant> <built-site-dir> <git-sha>
# Publishes a timestamped release and atomically repoints <env>/<variant>/current to it.
set -euo pipefail

ENV_NAME="${1:?usage: deploy.sh <dev|uat> <variant> <site-dir> <sha>}"
VARIANT="${2:?variant required}"
SRC="${3:?site dir required}"
SHA="${4:?sha required}"

BASE="${DEPLOY_BASE:-/var/www/knowledge-hub}"
KEEP_RELEASES=5

case "$ENV_NAME" in
  dev) PORT=8081 ;;
  uat) PORT=8080 ;;
  *) echo "Unknown environment: $ENV_NAME" >&2; exit 1 ;;
esac

[[ "$VARIANT" =~ ^[a-z0-9_-]+$ ]] || { echo "Invalid variant: $VARIANT" >&2; exit 1; }

TARGET_DIR="$BASE/$ENV_NAME/$VARIANT"
RELEASE="$TARGET_DIR/releases/$(date +%Y%m%d%H%M%S)-${SHA:0:7}"
PREVIOUS="$(readlink -f "$TARGET_DIR/current" 2>/dev/null || true)"

mkdir -p "$RELEASE"
cp -a "$SRC"/. "$RELEASE"/
echo "$VARIANT $SHA" > "$RELEASE/version.txt"

ln -sfn "$RELEASE" "$TARGET_DIR/current.tmp"
mv -Tf "$TARGET_DIR/current.tmp" "$TARGET_DIR/current"

# Verify nginx is serving this exact build; roll back otherwise.
if ! curl -fsS --retry 5 --retry-delay 2 "http://127.0.0.1:$PORT/$VARIANT/version.txt" | grep -q "$SHA"; then
  echo "Health check failed on port $PORT for $VARIANT" >&2
  if [ -n "$PREVIOUS" ] && [ -d "$PREVIOUS" ]; then
    ln -sfn "$PREVIOUS" "$TARGET_DIR/current.tmp"
    mv -Tf "$TARGET_DIR/current.tmp" "$TARGET_DIR/current"
    echo "Rolled back to $PREVIOUS" >&2
  fi
  exit 1
fi

# Keep only the newest releases for rollback.
ls -1dt "$TARGET_DIR"/releases/* | tail -n +$((KEEP_RELEASES + 1)) | xargs -r rm -rf

echo "Deployed ${SHA:0:7} to $ENV_NAME/$VARIANT on port $PORT"
