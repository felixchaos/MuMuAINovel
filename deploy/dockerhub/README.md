# Docker Hub 公开镜像部署

这个目录用于“只拉镜像、不本地构建”的部署方式。适合已经安装 Docker Desktop 或服务器上已经有 Docker Compose 的用户。

公开镜像：

```text
felixchaos/mumuainovel:v1.4.8-story-engine.1
felixchaos/mumuainovel:story-engine
felixchaos/mumuainovel:latest
```

## 使用方式

```bash
mkdir mumuainovel-story-engine
cd mumuainovel-story-engine
curl -fsSL -o docker-compose.yml https://raw.githubusercontent.com/felixchaos/MuMuAINovel/codex/official-compatible-story-engine/deploy/dockerhub/docker-compose.yml
curl -fsSL -o .env https://raw.githubusercontent.com/felixchaos/MuMuAINovel/codex/official-compatible-story-engine/deploy/dockerhub/.env.example
docker compose up -d
```

访问：

```text
http://localhost:8000
```

默认本地账号是 `admin / admin123`。首次使用建议修改 `.env` 里的 `LOCAL_AUTH_PASSWORD` 和 `POSTGRES_PASSWORD`。

如果 API Key、SMTP、注册开关等希望在网页里配置，可以先留空。

## 更新镜像

```bash
docker compose pull
docker compose up -d
```

## 从官方版本升级

如果机器上已经部署过官方 MuMuAINovel，请不要新建目录迁移。直接进入原官方部署目录，运行升级脚本，它会复用原来的 `.env` 和 PostgreSQL Docker volume：

```bash
curl -fsSL -o upgrade-to-story-engine.sh https://raw.githubusercontent.com/felixchaos/MuMuAINovel/codex/official-compatible-story-engine/deploy/upgrade/upgrade-to-story-engine.sh
bash upgrade-to-story-engine.sh
```

Windows PowerShell：

```powershell
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/felixchaos/MuMuAINovel/codex/official-compatible-story-engine/deploy/upgrade/upgrade-to-story-engine.ps1" -OutFile ".\upgrade-to-story-engine.ps1"
powershell -ExecutionPolicy Bypass -File .\upgrade-to-story-engine.ps1
```

脚本会先备份 compose 文件和 `.env`，并在 PostgreSQL 容器运行时导出一份 SQL 备份。不要手动执行 `docker compose down -v`，否则会删除数据库卷。

## 镜像发布

维护者发布镜像时使用：

```bash
DOCKERHUB_IMAGE=felixchaos/mumuainovel \
VERSION=v1.4.8-story-engine.1 \
deploy/dockerhub/publish-dockerhub.sh
```

如果 Docker Hub 或基础镜像拉取超时，可以让 buildx 的构建容器走宿主机代理：

```bash
DOCKER_BUILD_PROXY=http://host.docker.internal:7890 \
RESET_BUILDER=true \
DOCKERHUB_IMAGE=felixchaos/mumuainovel \
VERSION=v1.4.8-story-engine.1 \
deploy/dockerhub/publish-dockerhub.sh
```

脚本会发布 `VERSION`、`story-engine` 和 `latest` 三个 tag，并默认关闭赞助入口、公告弹窗、MuMu API 外链和右侧节日挂件。
