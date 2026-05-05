# 从官方 MuMuAINovel 升级到 Story Engine Fork

这个目录提供“原地升级”脚本，用于把已经部署好的官方 MuMuAINovel 切换到 `felixchaos/mumuainovel` Docker Hub 镜像。

脚本目标是保留用户数据：

- 不删除 Docker volume。
- 不执行 `docker compose down -v`。
- 保留原 `.env`，只补充 `MUMUAINOVEL_IMAGE`、`APP_VERSION` 和必要的 `NO_PROXY`。
- 替换前备份 `docker-compose.yml` / `compose.yml` 和 `.env`。
- 如果 PostgreSQL 容器正在运行，会额外导出一份 `postgres.sql`。

## 适用场景

- 用户当前是官方源码目录，通过 `docker compose up -d` 启动。
- 用户当前是官方 Docker Compose 部署目录，目录里有 `docker-compose.yml` 或 `compose.yml`。
- 用户希望保留已有项目、章节、角色、API 配置和上传数据，只升级应用版本。

不适用于：

- 手动裸机 Python/Node 部署。
- 数据库不是 compose 里的 `postgres` 服务，且没有改造脚本。
- 用户已经把数据库迁到外部 PostgreSQL，但 compose/.env 没有正确保留连接信息。

## macOS / Linux / WSL

进入现有官方 MuMuAINovel 部署目录，然后执行。不要新建空目录执行，否则 Docker Compose 项目名会变化，无法复用原来的数据库 volume。

```bash
curl -fsSL -o upgrade-to-story-engine.sh \
  https://raw.githubusercontent.com/felixchaos/MuMuAINovel/main/deploy/upgrade/upgrade-to-story-engine.sh

bash upgrade-to-story-engine.sh
```

无人值守：

```bash
bash upgrade-to-story-engine.sh --yes
```

如果拉取 GitHub 或 Docker Hub 很慢：

```bash
bash upgrade-to-story-engine.sh --proxy http://127.0.0.1:7890
```

跳过数据库 dump：

```bash
bash upgrade-to-story-engine.sh --yes --no-db-backup
```

## Windows PowerShell

进入现有官方 MuMuAINovel 部署目录，然后执行。不要在新目录里运行。

```powershell
Invoke-WebRequest `
  -Uri "https://raw.githubusercontent.com/felixchaos/MuMuAINovel/main/deploy/upgrade/upgrade-to-story-engine.ps1" `
  -OutFile ".\upgrade-to-story-engine.ps1"

powershell -ExecutionPolicy Bypass -File .\upgrade-to-story-engine.ps1
```

无人值守：

```powershell
powershell -ExecutionPolicy Bypass -File .\upgrade-to-story-engine.ps1 -Yes
```

使用代理：

```powershell
powershell -ExecutionPolicy Bypass -File .\upgrade-to-story-engine.ps1 -Proxy "http://127.0.0.1:7890"
```

## 升级后访问

默认访问地址不变：

```text
http://localhost:8000
```

如果原 `.env` 中设置了 `APP_PORT`，继续使用原端口。

## 回滚

脚本会创建类似下面的备份目录：

```text
backups/upgrade-story-engine-20260505-173000/
```

回滚 compose 文件：

```bash
cp backups/upgrade-story-engine-YYYYMMDD-HHMMSS/docker-compose.yml.bak docker-compose.yml
docker compose -f docker-compose.yml up -d
```

Windows PowerShell：

```powershell
Copy-Item "backups\upgrade-story-engine-YYYYMMDD-HHMMSS\docker-compose.yml.bak" ".\docker-compose.yml" -Force
docker compose -f ".\docker-compose.yml" up -d
```

注意：应用升级后可能会执行数据库迁移。脚本会尽量提前导出 `postgres.sql`，但旧官方版本不一定能理解新字段。真正要完整回退数据库，需要用备份 SQL 恢复 PostgreSQL。
