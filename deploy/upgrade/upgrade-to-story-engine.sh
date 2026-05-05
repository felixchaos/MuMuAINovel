#!/usr/bin/env bash
set -Eeuo pipefail

VERSION="${VERSION:-v1.4.8-story-engine.2}"
IMAGE="${IMAGE:-felixchaos/mumuainovel:${VERSION}}"
BRANCH="${BRANCH:-main}"
RAW_BASE="${RAW_BASE:-https://raw.githubusercontent.com/felixchaos/MuMuAINovel/${BRANCH}}"
COMPOSE_URL="${COMPOSE_URL:-${RAW_BASE}/deploy/dockerhub/docker-compose.yml}"
ENV_URL="${ENV_URL:-${RAW_BASE}/deploy/dockerhub/.env.example}"

ASSUME_YES=false
SKIP_DB_BACKUP=false
DRY_RUN=false
PROXY_URL="${PROXY_URL:-}"

usage() {
  cat <<EOF
Upgrade an official MuMuAINovel Docker/Compose deployment to Felix's story-engine fork.

Run this inside the existing MuMuAINovel deployment directory.

Usage:
  bash upgrade-to-story-engine.sh [options]

Options:
  -y, --yes             Run without confirmation prompts.
      --no-db-backup    Skip pg_dump backup before switching compose file.
      --dry-run         Show detected settings and exit before changing files.
      --image IMAGE     Target image. Default: ${IMAGE}
      --proxy URL       Proxy for downloads/pulls, e.g. http://127.0.0.1:7890.
  -h, --help            Show this help.

Safety:
  - This script never runs "docker compose down -v".
  - It backs up docker-compose.yml/compose.yml and .env before editing.
  - It reuses the existing postgres_data Docker volume when run in the same directory.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    -y|--yes) ASSUME_YES=true ;;
    --no-db-backup) SKIP_DB_BACKUP=true ;;
    --dry-run) DRY_RUN=true ;;
    --image)
      if [ "${2:-}" = "" ]; then
        echo "--image requires a value." >&2
        exit 1
      fi
      IMAGE="$2"
      shift
      ;;
    --proxy)
      if [ "${2:-}" = "" ]; then
        echo "--proxy requires a value." >&2
        exit 1
      fi
      PROXY_URL="$2"
      shift
      ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
  shift
done

if [ -z "$IMAGE" ]; then
  echo "IMAGE cannot be empty." >&2
  exit 1
fi

if [ -n "$PROXY_URL" ]; then
  export HTTP_PROXY="$PROXY_URL"
  export HTTPS_PROXY="$PROXY_URL"
  export http_proxy="$PROXY_URL"
  export https_proxy="$PROXY_URL"
fi

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif docker-compose version >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  echo "Docker Compose is not available. Install Docker Desktop or Docker Compose first." >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon is not running. Start Docker Desktop or Docker Engine first." >&2
  exit 1
fi

if [ -f docker-compose.yml ]; then
  COMPOSE_FILE="docker-compose.yml"
elif [ -f compose.yml ]; then
  COMPOSE_FILE="compose.yml"
elif [ -f compose.yaml ]; then
  COMPOSE_FILE="compose.yaml"
else
  echo "No docker-compose.yml/compose.yml found in current directory: $(pwd)" >&2
  echo "Please run this script inside the existing MuMuAINovel deployment directory." >&2
  exit 1
fi

download() {
  local url="$1"
  local output="$2"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$url" -o "$output"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$output" "$url"
  else
    echo "curl or wget is required to download ${url}" >&2
    exit 1
  fi
}

upsert_env() {
  local key="$1"
  local value="$2"
  local tmp
  tmp="$(mktemp)"
  if [ -f .env ] && grep -q "^${key}=" .env; then
    awk -v key="$key" -v value="$value" '
      BEGIN { done = 0 }
      $0 ~ "^" key "=" { print key "=" value; done = 1; next }
      { print }
      END { if (!done) print key "=" value }
    ' .env > "$tmp"
    mv "$tmp" .env
  else
    [ -f .env ] || touch .env
    printf '\n%s=%s\n' "$key" "$value" >> .env
    rm -f "$tmp"
  fi
}

read_env_value() {
  local key="$1"
  local default="$2"
  if [ -f .env ]; then
    local line
    line="$(grep -E "^${key}=" .env | tail -n 1 || true)"
    if [ -n "$line" ]; then
      local value
      value="${line#*=}"
      value="${value%$'\r'}"
      value="${value%\"}"
      value="${value#\"}"
      value="${value%\'}"
      value="${value#\'}"
      printf '%s\n' "$value"
      return
    fi
  fi
  printf '%s\n' "$default"
}

BACKUP_DIR="backups/upgrade-story-engine-$(date +%Y%m%d-%H%M%S)"

echo "Current directory: $(pwd)"
echo "Compose file:      ${COMPOSE_FILE}"
echo "Target image:      ${IMAGE}"
echo "Backup dir:        ${BACKUP_DIR}"
echo "Proxy:             ${PROXY_URL:-<none>}"

if [ "$DRY_RUN" = true ]; then
  echo "Dry run complete. No files changed."
  exit 0
fi

if [ "$ASSUME_YES" != true ]; then
  printf '\nThis will replace %s with the story-engine Docker Hub compose file, preserving .env and Docker volumes. Continue? [y/N] ' "$COMPOSE_FILE"
  read -r answer
  case "$answer" in
    y|Y|yes|YES) ;;
    *) echo "Cancelled."; exit 0 ;;
  esac
fi

mkdir -p "$BACKUP_DIR"
cp "$COMPOSE_FILE" "${BACKUP_DIR}/${COMPOSE_FILE}.bak"
if [ -f .env ]; then
  cp .env "${BACKUP_DIR}/.env.bak"
else
  download "$ENV_URL" .env
  cp .env "${BACKUP_DIR}/.env.generated.bak"
fi

"${COMPOSE[@]}" -f "$COMPOSE_FILE" ps > "${BACKUP_DIR}/compose-ps-before.txt" 2>&1 || true
docker volume ls > "${BACKUP_DIR}/docker-volumes-before.txt" 2>&1 || true

POSTGRES_DB="$(read_env_value POSTGRES_DB mumuai_novel)"
POSTGRES_USER="$(read_env_value POSTGRES_USER mumuai)"

if [ "$SKIP_DB_BACKUP" != true ]; then
  POSTGRES_CID="$("${COMPOSE[@]}" -f "$COMPOSE_FILE" ps -q postgres 2>/dev/null || true)"
  if [ -n "$POSTGRES_CID" ]; then
    echo "Creating PostgreSQL SQL backup..."
    if "${COMPOSE[@]}" -f "$COMPOSE_FILE" exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" > "${BACKUP_DIR}/postgres.sql"; then
      echo "Database backup saved: ${BACKUP_DIR}/postgres.sql"
    else
      echo "Warning: PostgreSQL backup failed. File backups are still available in ${BACKUP_DIR}." >&2
      if [ "$ASSUME_YES" != true ]; then
        printf 'Continue without database dump? [y/N] '
        read -r answer
        case "$answer" in
          y|Y|yes|YES) ;;
          *) echo "Cancelled."; exit 1 ;;
        esac
      fi
    fi
  else
    echo "PostgreSQL service is not currently running; skipping pg_dump backup."
  fi
else
  echo "Skipping PostgreSQL backup by request."
fi

TMP_COMPOSE="$(mktemp)"
download "$COMPOSE_URL" "$TMP_COMPOSE"
cp "$TMP_COMPOSE" "$COMPOSE_FILE"
rm -f "$TMP_COMPOSE"

upsert_env "MUMUAINOVEL_IMAGE" "$IMAGE"
upsert_env "APP_VERSION" "${VERSION#v}"

if ! grep -q '^NO_PROXY=' .env; then
  upsert_env "NO_PROXY" "localhost,127.0.0.1,postgres,host.docker.internal"
elif ! grep -q '^NO_PROXY=.*postgres' .env; then
  current_no_proxy="$(read_env_value NO_PROXY localhost,127.0.0.1)"
  upsert_env "NO_PROXY" "${current_no_proxy},postgres,host.docker.internal"
fi

echo "Pulling target images..."
"${COMPOSE[@]}" -f "$COMPOSE_FILE" pull

echo "Starting upgraded services..."
"${COMPOSE[@]}" -f "$COMPOSE_FILE" up -d --remove-orphans

"${COMPOSE[@]}" -f "$COMPOSE_FILE" ps

APP_PORT="$(read_env_value APP_PORT 8000)"
echo
echo "Upgrade complete."
echo "Open: http://localhost:${APP_PORT}"
echo "Backups: ${BACKUP_DIR}"
echo
echo "Rollback compose file only:"
echo "  cp '${BACKUP_DIR}/${COMPOSE_FILE}.bak' '${COMPOSE_FILE}'"
echo "  docker compose -f '${COMPOSE_FILE}' up -d"
echo
echo "Do not run docker compose down -v unless you intentionally want to delete database volumes."
