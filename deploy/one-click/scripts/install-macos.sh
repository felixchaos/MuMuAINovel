#!/usr/bin/env bash
set -e

FORK_VERSION="v1.4.8-story-engine.1"
ROOT_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"
STATE_DIR="$ROOT_DIR/.oneclick"
STATE_FILE="$STATE_DIR/oneclick.env"
APP_PORT_DEFAULT="8000"
POSTGRES_PORT_DEFAULT="5432"

mkdir -p "$STATE_DIR"
cd "$ROOT_DIR"

log() {
  printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$*"
}

warn() {
  printf '\n[提示] %s\n' "$*"
}

ask() {
  local prompt="$1"
  local default_value="${2:-}"
  local answer
  if [ -n "$default_value" ]; then
    read -r -p "$prompt [$default_value]: " answer
    printf '%s' "${answer:-$default_value}"
  else
    read -r -p "$prompt: " answer
    printf '%s' "$answer"
  fi
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

random_password() {
  LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 24
}

get_state() {
  local key="$1"
  [ -f "$STATE_FILE" ] || return 0
  awk -F= -v k="$key" '$1 == k {print substr($0, length(k) + 2)}' "$STATE_FILE" | tail -n 1
}

set_state() {
  local key="$1"
  local value="$2"
  local tmp
  tmp="$(mktemp)"
  if [ -f "$STATE_FILE" ]; then
    awk -v k="$key" -v line="$key=$value" '
      BEGIN { done = 0 }
      $0 ~ "^" k "=" { print line; done = 1; next }
      { print }
      END { if (!done) print line }
    ' "$STATE_FILE" >"$tmp"
  else
    printf '%s=%s\n' "$key" "$value" >"$tmp"
  fi
  mv "$tmp" "$STATE_FILE"
}

set_env_var() {
  local key="$1"
  local value="$2"
  local tmp
  touch "$ENV_FILE"
  tmp="$(mktemp)"
  awk -v k="$key" -v line="$key=$value" '
    BEGIN { done = 0 }
    $0 ~ "^" k "=" { print line; done = 1; next }
    { print }
    END { if (!done) print line }
  ' "$ENV_FILE" >"$tmp"
  mv "$tmp" "$ENV_FILE"
}

env_value() {
  local key="$1"
  [ -f "$ENV_FILE" ] || return 0
  awk -F= -v k="$key" '$1 == k {print substr($0, length(k) + 2)}' "$ENV_FILE" | tail -n 1
}

env_or_default() {
  local key="$1"
  local default_value="$2"
  local current
  current="$(env_value "$key" || true)"
  if [ -n "$current" ]; then
    printf '%s' "$current"
  else
    printf '%s' "$default_value"
  fi
}

write_default_env() {
  local db_password
  db_password="$(random_password)"
  cat >"$ENV_FILE" <<EOF
APP_NAME=MuMuAINovel
APP_VERSION=${FORK_VERSION#v}
TZ=Asia/Shanghai
DEBUG=false

POSTGRES_DB=mumuai_novel
POSTGRES_USER=mumuai
POSTGRES_PASSWORD=$db_password
POSTGRES_PORT=$POSTGRES_PORT_DEFAULT

APP_PORT=$APP_PORT_DEFAULT
FRONTEND_URL=http://localhost:$APP_PORT_DEFAULT
SESSION_COOKIE_SECURE=false

LOCAL_AUTH_ENABLED=true
LOCAL_AUTH_USERNAME=admin
LOCAL_AUTH_PASSWORD=admin123
LOCAL_AUTH_DISPLAY_NAME=本地管理员

EMAIL_AUTH_ENABLED=false
EMAIL_REGISTER_ENABLED=false

OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.openai.com/v1
GEMINI_API_KEY=
GEMINI_BASE_URL=
ANTHROPIC_API_KEY=
ANTHROPIC_BASE_URL=
DEFAULT_AI_PROVIDER=openai
DEFAULT_MODEL=gpt-4o-mini
DEFAULT_TEMPERATURE=0.7
DEFAULT_MAX_TOKENS=32000

SMTP_PROVIDER=
SMTP_HOST=
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM_EMAIL=
SMTP_FROM_NAME=MuMuAINovel

HTTP_PROXY=
HTTPS_PROXY=
NO_PROXY=localhost,127.0.0.1,postgres,host.docker.internal
EOF
}

configure_env_interactive() {
  log "进入可选配置引导。所有项目都可以直接回车跳过。"

  local app_port db_port admin_user admin_password ai_provider api_key base_url model

  app_port="$(ask '网页端口' "$(env_or_default APP_PORT "$APP_PORT_DEFAULT")")"
  db_port="$(ask 'PostgreSQL 本机端口' "$(env_or_default POSTGRES_PORT "$POSTGRES_PORT_DEFAULT")")"
  admin_user="$(ask '本地管理员账号' "$(env_or_default LOCAL_AUTH_USERNAME 'admin')")"
  admin_password="$(ask '本地管理员密码' "$(env_or_default LOCAL_AUTH_PASSWORD 'admin123')")"

  set_env_var APP_PORT "$app_port"
  set_env_var FRONTEND_URL "http://localhost:$app_port"
  set_env_var POSTGRES_PORT "$db_port"
  set_env_var LOCAL_AUTH_USERNAME "$admin_user"
  set_env_var LOCAL_AUTH_PASSWORD "$admin_password"
  set_env_var SESSION_COOKIE_SECURE "false"

  echo
  echo "AI 配置可以之后在网页 API 设置里填写。这里留空即跳过。"
  ai_provider="$(ask '默认 AI 提供商(openai/gemini/anthropic)' "$(env_or_default DEFAULT_AI_PROVIDER 'openai')")"
  model="$(ask '默认模型名' "$(env_or_default DEFAULT_MODEL 'gpt-4o-mini')")"
  api_key="$(ask 'OpenAI/OpenRouter API Key，可留空' '')"
  base_url="$(ask 'OpenAI 兼容 API 地址' "$(env_or_default OPENAI_BASE_URL 'https://api.openai.com/v1')")"

  set_env_var DEFAULT_AI_PROVIDER "$ai_provider"
  set_env_var DEFAULT_MODEL "$model"
  [ -n "$api_key" ] && set_env_var OPENAI_API_KEY "$api_key"
  set_env_var OPENAI_BASE_URL "$base_url"
}

probe_url() {
  local url="$1"
  curl -fsSL --connect-timeout 8 --max-time 12 "$url" >/dev/null 2>&1
}

configure_proxy() {
  local force="${1:-false}"
  local saved_enabled saved_host saved_port answer proxy_host proxy_port host_proxy docker_proxy

  saved_enabled="$(get_state PROXY_ENABLED || true)"
  saved_host="$(get_state PROXY_HOST || true)"
  saved_port="$(get_state PROXY_PORT || true)"

  if [ "$force" != "true" ] && [ "$saved_enabled" = "true" ] && [ -n "$saved_port" ]; then
    answer="$(ask "检测到已保存代理 $saved_host:$saved_port，是否继续使用？(y/n)" "y")"
    if [ "$answer" = "y" ] || [ "$answer" = "Y" ]; then
      proxy_host="$saved_host"
      proxy_port="$saved_port"
    fi
  fi

  if [ -z "${proxy_port:-}" ]; then
    if [ "$force" != "true" ] && probe_url "https://github.com"; then
      answer="$(ask 'GitHub 访问正常，是否仍启用局域网代理？(y/n)' 'n')"
      if [ "$answer" != "y" ] && [ "$answer" != "Y" ]; then
        set_state PROXY_ENABLED "false"
        set_env_var HTTP_PROXY ""
        set_env_var HTTPS_PROXY ""
        return 0
      fi
    else
      warn "GitHub 或依赖源访问可能较慢，建议启用局域网代理。"
    fi

    proxy_host="$(ask '代理主机，通常是 127.0.0.1' "${saved_host:-127.0.0.1}")"
    proxy_port="$(ask '代理端口，例如 7890/7897/10809' "${saved_port:-7890}")"
  fi

  host_proxy="http://$proxy_host:$proxy_port"
  if [ "$proxy_host" = "127.0.0.1" ] || [ "$proxy_host" = "localhost" ]; then
    docker_proxy="http://host.docker.internal:$proxy_port"
  else
    docker_proxy="$host_proxy"
  fi

  export HTTP_PROXY="$host_proxy"
  export HTTPS_PROXY="$host_proxy"
  export ALL_PROXY="$host_proxy"
  export http_proxy="$host_proxy"
  export https_proxy="$host_proxy"
  export all_proxy="$host_proxy"
  export NO_PROXY="localhost,127.0.0.1,postgres,host.docker.internal"
  export no_proxy="$NO_PROXY"
  export ONECLICK_DOCKER_PROXY="$docker_proxy"

  set_env_var HTTP_PROXY "$docker_proxy"
  set_env_var HTTPS_PROXY "$docker_proxy"
  set_env_var NO_PROXY "localhost,127.0.0.1,postgres,host.docker.internal"
  set_state PROXY_ENABLED "true"
  set_state PROXY_HOST "$proxy_host"
  set_state PROXY_PORT "$proxy_port"

  log "已启用代理：宿主机 $host_proxy，容器 $docker_proxy"
}

ensure_docker() {
  if ! command_exists docker; then
    warn "未检测到 Docker Desktop。"
    if command_exists brew; then
      local install
      install="$(ask '是否使用 Homebrew 安装 Docker Desktop？(y/n)' 'y')"
      if [ "$install" = "y" ] || [ "$install" = "Y" ]; then
        brew install --cask docker
      else
        open "https://www.docker.com/products/docker-desktop/"
        read -r -p "安装 Docker Desktop 并启动后，按回车继续..."
      fi
    else
      open "https://www.docker.com/products/docker-desktop/"
      read -r -p "请安装 Docker Desktop 并启动后，按回车继续..."
    fi
  fi

  if ! docker info >/dev/null 2>&1; then
    warn "Docker Desktop 尚未启动，正在尝试打开。"
    open -a Docker >/dev/null 2>&1 || true
  fi

  local i
  for i in $(seq 1 90); do
    if docker info >/dev/null 2>&1; then
      log "Docker 已就绪。"
      return 0
    fi
    printf '.'
    sleep 2
  done

  echo
  echo "Docker Desktop 未就绪。请手动打开 Docker Desktop，等它显示 Running 后重新运行本脚本。"
  exit 1
}

detect_compose() {
  if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
  elif command_exists docker-compose; then
    COMPOSE=(docker-compose)
  else
    echo "未检测到 docker compose。请更新 Docker Desktop 后重新运行。"
    exit 1
  fi
}

compose() {
  "${COMPOSE[@]}" "$@"
}

build_and_start() {
  local mirror_answer use_cn_mirror app_port health_url
  local build_args
  mirror_answer="$(ask '是否启用国内构建镜像源以加速 npm/pip/apt？(y/n)' "$(get_state USE_CN_MIRROR || printf 'n')")"
  if [ "$mirror_answer" = "y" ] || [ "$mirror_answer" = "Y" ]; then
    use_cn_mirror="true"
  else
    use_cn_mirror="false"
  fi
  set_state USE_CN_MIRROR "$mirror_answer"

  build_args=(
    --build-arg "USE_CN_MIRROR=$use_cn_mirror"
    --build-arg "VITE_ENABLE_SPONSOR=false"
    --build-arg "VITE_ENABLE_ANNOUNCEMENT_MODAL=false"
    --build-arg "VITE_ENABLE_MUMU_API_LINKS=false"
    --build-arg "VITE_ENABLE_SPRING_FESTIVAL=false"
    --build-arg "VITE_DISABLE_PROMO_FEATURES=true"
    --build-arg "VITE_DEPLOY_PROFILE=oneclick"
  )

  if [ -n "${ONECLICK_DOCKER_PROXY:-}" ]; then
    build_args+=(--build-arg "HTTP_PROXY=$ONECLICK_DOCKER_PROXY" --build-arg "HTTPS_PROXY=$ONECLICK_DOCKER_PROXY")
    build_args+=(--build-arg "http_proxy=$ONECLICK_DOCKER_PROXY" --build-arg "https_proxy=$ONECLICK_DOCKER_PROXY")
  fi

  log "开始构建镜像。这一步首次运行会比较久。"
  DOCKER_BUILDKIT=1 compose build "${build_args[@]}"

  log "启动服务。"
  compose up -d

  app_port="$(env_or_default APP_PORT "$APP_PORT_DEFAULT")"
  health_url="http://localhost:$app_port/health"

  log "等待服务健康检查。"
  local i
  for i in $(seq 1 90); do
    if curl -fsS "$health_url" >/dev/null 2>&1; then
      log "启动完成： http://localhost:$app_port"
      open "http://localhost:$app_port" >/dev/null 2>&1 || true
      echo
      echo "默认本地账号：admin / admin123（如果你在引导里改过，请使用新账号密码）"
      echo "配置文件：$ENV_FILE"
      echo "常用日志：docker compose logs -f"
      return 0
    fi
    printf '.'
    sleep 2
  done

  echo
  warn "服务还没有通过健康检查，请查看日志：docker compose logs -f"
}

main() {
  log "MuMuAINovel Story Engine 一键部署 $FORK_VERSION"

  local choice
  if [ -f "$ENV_FILE" ]; then
    choice="$(ask '检测到已有 .env。回车直接启动，输入 c 重新配置，输入 p 设置代理，输入 q 退出' '')"
    case "$choice" in
      q|Q) exit 0 ;;
      c|C) configure_env_interactive ;;
      p|P) configure_proxy true ;;
      *) ;;
    esac
  else
    echo
    echo "请选择启动方式："
    echo "1. 完全跳过配置，使用默认本地配置启动"
    echo "2. 进入可选配置引导"
    echo "3. 先设置代理，再使用默认配置启动"
    choice="$(ask '输入序号' '1')"
    write_default_env
    case "$choice" in
      2) configure_env_interactive ;;
      3) configure_proxy true ;;
      *) ;;
    esac
  fi

  configure_proxy false
  ensure_docker
  detect_compose
  build_and_start
}

main "$@"
