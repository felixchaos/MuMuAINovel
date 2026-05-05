#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
DOCKERHUB_IMAGE="${DOCKERHUB_IMAGE:-felixchaos/mumuainovel}"
VERSION="${VERSION:-v1.4.8-story-engine.1}"
PLATFORMS="${PLATFORMS:-linux/amd64,linux/arm64}"
PUSH="${PUSH:-true}"
BUILDER_NAME="${BUILDER_NAME:-mumuainovel-builder}"

cd "$ROOT_DIR"

if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon 未启动。请先打开 Docker Desktop 或启动 Docker 服务。"
  exit 1
fi

if ! docker buildx version >/dev/null 2>&1; then
  echo "未检测到 docker buildx。macOS 可运行：brew install docker-buildx"
  exit 1
fi

if ! docker buildx inspect "$BUILDER_NAME" >/dev/null 2>&1; then
  docker buildx create --name "$BUILDER_NAME" --driver docker-container --use
else
  docker buildx use "$BUILDER_NAME"
fi

docker buildx inspect --bootstrap >/dev/null

tags=(
  "--tag" "$DOCKERHUB_IMAGE:$VERSION"
  "--tag" "$DOCKERHUB_IMAGE:story-engine"
  "--tag" "$DOCKERHUB_IMAGE:latest"
)

output_args=("--push")
if [ "$PUSH" != "true" ]; then
  output_args=("--load")
  PLATFORMS="${PLATFORMS%%,*}"
fi

docker buildx build \
  --platform "$PLATFORMS" \
  "${tags[@]}" \
  --label "org.opencontainers.image.title=MuMuAINovel Story Engine Fork" \
  --label "org.opencontainers.image.description=Official-compatible MuMuAINovel fork with story-engine, book import, rewrite, and deployment enhancements." \
  --label "org.opencontainers.image.source=https://github.com/felixchaos/MuMuAINovel" \
  --label "org.opencontainers.image.version=$VERSION" \
  --build-arg "USE_CN_MIRROR=${USE_CN_MIRROR:-false}" \
  --build-arg "VITE_ENABLE_SPONSOR=false" \
  --build-arg "VITE_ENABLE_ANNOUNCEMENT_MODAL=false" \
  --build-arg "VITE_ENABLE_MUMU_API_LINKS=false" \
  --build-arg "VITE_ENABLE_SPRING_FESTIVAL=false" \
  --build-arg "VITE_DISABLE_PROMO_FEATURES=true" \
  --build-arg "VITE_DEPLOY_PROFILE=dockerhub" \
  "${output_args[@]}" \
  .

echo "Docker image published:"
echo "  $DOCKERHUB_IMAGE:$VERSION"
echo "  $DOCKERHUB_IMAGE:story-engine"
echo "  $DOCKERHUB_IMAGE:latest"
