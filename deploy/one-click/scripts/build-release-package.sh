#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:-v1.4.8-story-engine.1}"
ROOT_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"
PACKAGE_BASENAME="MuMuAINovel-StoryEngine-OneClick-${VERSION}"
PACKAGE_PATH="$DIST_DIR/${PACKAGE_BASENAME}.zip"

cd "$ROOT_DIR"

mkdir -p "$DIST_DIR"
rm -f "$PACKAGE_PATH"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "必须在 git 工作区内构建 release 包。"
  exit 1
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

git archive --format=tar --prefix="${PACKAGE_BASENAME}/" HEAD | tar -x -C "$TMP_DIR"

chmod +x "$TMP_DIR/${PACKAGE_BASENAME}/deploy/one-click/MuMuAINovel-OneClick-macOS.command" || true
chmod +x "$TMP_DIR/${PACKAGE_BASENAME}/deploy/one-click/scripts/install-macos.sh" || true
chmod +x "$TMP_DIR/${PACKAGE_BASENAME}/deploy/one-click/scripts/build-release-package.sh" || true

(
  cd "$TMP_DIR"
  zip -qr "$PACKAGE_PATH" "$PACKAGE_BASENAME"
)

echo "$PACKAGE_PATH"
