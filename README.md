# MuMuAINovel Enhanced Fork

基于 [xiamuceer-j/MuMuAINovel](https://github.com/xiamuceer-j/MuMuAINovel) 的个人增强版 fork，目标是在保持官方版本兼容性的基础上，补强长篇小说创作里的剧情工程能力、章节重写流程、后台任务可控性和多人部署体验。

本仓库不是官方发行版。需要最稳定的官方版本时，请优先查看上游仓库；需要本 fork 的增强功能时，可以按本文档从源码部署。

## 这个 Fork 做了什么

- 保留官方核心能力：项目管理、世界观、角色/组织、章节、大纲、伏笔、提示词、MCP 插件、LinuxDO OAuth、本地账户登录。
- 增强大纲生成/续写：续写时补充前文、角色、组织、关系、职业等上下文，并提高 JSON 输出上限；解析失败时停止写库，避免把坏数据写进项目。
- 增强章节工作流：支持章节分析失败原因透传、Gemini 拦截/空响应识别、全章重写与局部重写的上下文收敛。
- 增强章节编辑：章节管理支持手动新建章节、单章导入、批量导入、TXT/Markdown 智能拆分导入，并支持冲突跳过或覆盖。
- 增强 AI 编辑：章节标题和摘要支持 AI 生成/润色；章节正文支持全文润色、全文重写和选中片段编辑。
- 增强润色工作流：文本框内润色支持填写用户要求，结果流式显示，生成后先确认，再决定是否应用，避免直接覆盖原文。
- 增强角色/组织/大纲优化：尽量复用已有后台任务、AI 调用和历史记录流程，而不是另起一套孤立逻辑。
- 增强导入导出：TXT 拆书解析更稳，章节导出支持范围选择和分章 ZIP，便于上传到写作平台。
- 增强部署体验：支持管理员在网页里维护 SMTP 与注册开关，适合个人或小团队自部署。
- 增强模型体验：模型列表接口带缓存，大纲弹窗不再等待模型列表加载完才出现。

## 快速部署

推荐使用 Docker Compose 从源码构建。不要直接使用官方 Docker Hub 镜像来部署本 fork，因为镜像可能不包含本 fork 的改动。

```bash
git clone -b codex/official-compatible-story-engine https://github.com/felixchaos/MuMuAINovel.git
cd MuMuAINovel
cp backend/.env.example .env
```

编辑 `.env`，至少修改下面这些项：

```env
POSTGRES_PASSWORD=change_this_database_password

LOCAL_AUTH_ENABLED=true
LOCAL_AUTH_USERNAME=admin
LOCAL_AUTH_PASSWORD=change_this_admin_password
LOCAL_AUTH_DISPLAY_NAME=本地管理员

OPENAI_API_KEY=your_api_key
OPENAI_BASE_URL=https://api.openai.com/v1
DEFAULT_AI_PROVIDER=openai
DEFAULT_MODEL=gpt-4o-mini

FRONTEND_URL=http://localhost:8000
SESSION_COOKIE_SECURE=false
EMAIL_REGISTER_ENABLED=false
```

如果使用 OpenRouter 这类 OpenAI 兼容接口，可以这样填：

```env
OPENAI_API_KEY=your_openrouter_key
OPENAI_BASE_URL=https://openrouter.ai/api/v1
DEFAULT_AI_PROVIDER=openai
DEFAULT_MODEL=deepseek/deepseek-v4-pro
```

本地启动：

```bash
docker compose build
docker compose up -d
```

访问：

```text
http://localhost:8000
```

默认账号取决于 `.env` 中的 `LOCAL_AUTH_USERNAME` 和 `LOCAL_AUTH_PASSWORD`。首次部署后建议立即改掉默认密码。

## 个人部署推荐构建方式

如果构建网络较慢，可以尝试国内镜像参数：

```bash
docker compose build --build-arg USE_CN_MIRROR=true
docker compose up -d
```

## 常用命令

```bash
# 查看容器状态
docker compose ps

# 查看日志
docker compose logs -f

# 重启服务
docker compose restart

# 停止服务
docker compose down

# 更新当前分支代码后重新构建
git pull
docker compose build
docker compose up -d
```

## 环境变量说明

### 登录与注册

| 变量 | 说明 |
| --- | --- |
| `LOCAL_AUTH_ENABLED` | 是否启用本地管理员登录 |
| `LOCAL_AUTH_USERNAME` | 本地管理员账号 |
| `LOCAL_AUTH_PASSWORD` | 本地管理员密码 |
| `SESSION_COOKIE_SECURE` | HTTPS 部署建议 `true`；本地 HTTP 访问设为 `false` |
| `EMAIL_AUTH_ENABLED` | 是否启用邮箱验证码登录 |
| `EMAIL_REGISTER_ENABLED` | 初始注册开关；管理员也可以在网页系统设置里维护 |

关闭注册后，已有用户仍可登录；新邮箱注册和首次 LinuxDO 登录创建账号会被拒绝。

### AI 模型

| 变量 | 说明 |
| --- | --- |
| `OPENAI_API_KEY` | OpenAI 或 OpenAI 兼容接口 Key |
| `OPENAI_BASE_URL` | OpenAI 兼容接口地址 |
| `GEMINI_API_KEY` | Gemini Key |
| `GEMINI_BASE_URL` | Gemini 兼容地址，可留空 |
| `ANTHROPIC_API_KEY` | Claude Key |
| `ANTHROPIC_BASE_URL` | Claude 兼容地址，可留空 |
| `DEFAULT_AI_PROVIDER` | 默认提供商，例如 `openai`、`gemini`、`anthropic` |
| `DEFAULT_MODEL` | 默认模型名 |
| `DEFAULT_MAX_TOKENS` | 默认最大输出 Token |

AI Key 是用户级配置。管理员可以先配置自己的 Key；其他用户登录后可以在 API 设置里配置自己的模型和 Key。

### SMTP

系统 SMTP 用于邮箱验证码登录、注册和找回密码。生产部署建议在网页的“系统设置”里由管理员维护 SMTP 信息，不要把真实 SMTP 密钥提交到仓库。

| 变量 | 说明 |
| --- | --- |
| `SMTP_PROVIDER` | SMTP 服务商标识 |
| `SMTP_HOST` | SMTP 主机 |
| `SMTP_PORT` | SMTP 端口 |
| `SMTP_USERNAME` | SMTP 用户名 |
| `SMTP_PASSWORD` | SMTP 密码或授权码 |
| `SMTP_FROM_EMAIL` | 发件邮箱 |
| `SMTP_FROM_NAME` | 发件名称 |

## Cloudflare / 反向代理

本仓库包含一个可选的 Cloudflare Worker 智能路由示例，位于 `deploy/cloudflare/novelai-router`。它的用途是：

- 让入口域名根据访问地区路由到不同源站。
- API 请求固定到主后端，避免登录态和数据库写入分裂。
- 静态资源使用 Cloudflare 缓存，HTML 和 API 保持动态。

使用前请把 `wrangler.jsonc` 中的域名和变量改成自己的，不要直接提交个人服务器 IP、私有域名、Token 或证书。

```bash
cd deploy/cloudflare/novelai-router
npx wrangler deploy --dry-run
npx wrangler deploy
```

普通个人部署不需要 Worker，直接用 Nginx、Caddy 或 Cloudflare DNS 代理到单台服务器即可。

## 本地开发

### 后端

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端开发服务器默认代理 `/api` 到 `http://localhost:8000`。

生产构建：

```bash
cd frontend
npm run build
```

默认会输出到 `backend/static`，由后端统一托管。

## 常见问题

### 章节管理能不能直接导入或新建章节

可以。章节管理页面提供“新建章节”和“导入章节”：

- 新建章节：适合手动复制正文、补录单章内容，也可以先填写正文再让 AI 生成标题和摘要。
- 导入章节：支持上传一个或多个 TXT/Markdown 文件；可以按文件作为章节，也可以让系统按章节标题智能拆分。
- 冲突处理：导入到已有章节序号时，可以选择跳过，或覆盖旧章节并清理旧分析结果。

### 章节标题、摘要和正文支持哪些 AI 编辑

章节编辑器和新建章节弹窗都支持章节级 AI 辅助：

- 标题：根据正文、摘要和关联大纲生成标题，也可以润色已有标题。
- 摘要：根据正文生成摘要，也可以润色已有摘要。
- 正文：支持全文润色、全文重写和选中片段编辑。

这些工具会先让你填写本次要求，生成结果会实时显示，完成后点击“应用结果”才会写回表单。

### 登录后又跳回登录页

如果是本地 HTTP 访问，请确认：

```env
SESSION_COOKIE_SECURE=false
FRONTEND_URL=http://localhost:8000
```

如果是 HTTPS 域名部署，建议：

```env
SESSION_COOKIE_SECURE=true
FRONTEND_URL=https://your-domain.example
```

### 页面显示“注册暂未开放”

管理员进入“系统设置”打开“允许新用户注册”。如果页面仍然显示关闭，检查：

- 后端是否已经重启。
- `/api/auth/config` 返回的 `email_register_enabled` 是否为 `true`。
- 浏览器是否缓存了旧页面，尝试强制刷新。

### 大纲续写提示 JSON 解析失败

本 fork 不再把解析失败的 AI 原文强行写入数据库。遇到这个提示时，说明模型没有返回完整 JSON。建议：

- 降低一次生成章节数。
- 换更稳定的模型。
- 提高模型输出上限。
- 简化用户要求，避免让模型输出解释性文字。

### 润色按钮会不会直接覆盖原文

不会。文本框内润色会先让你填写润色要求，随后流式展示生成结果，点击确认后才会替换原内容。

### 数据库可以暴露公网吗

不建议。PostgreSQL 应只允许容器内网、内网或受控隧道访问。公网暴露数据库会带来爆破、撞库、未授权访问和数据泄露风险。

## 安全建议

- 不要提交 `.env`、数据库备份、API Key、SMTP 密钥、Cloudflare Token、SSH 私钥。
- 生产环境务必修改默认数据库密码和管理员密码。
- 不要把 PostgreSQL 直接暴露到公网。
- 多人使用时建议关闭公开注册，由管理员创建账号或短时间开放注册。
- 给朋友部署时，建议让每个用户自己在网页里配置 AI API Key。

## 项目结构

```text
.
├── backend/                 # FastAPI 后端、数据库模型、AI 服务与迁移
├── frontend/                # React + TypeScript 前端
├── deploy/cloudflare/       # 可选 Cloudflare Worker 路由示例
├── docker-compose.yml       # Docker Compose 编排
├── Dockerfile               # 前后端一体镜像构建
└── README.md
```

## 上游与许可证

上游项目：[xiamuceer-j/MuMuAINovel](https://github.com/xiamuceer-j/MuMuAINovel)

本 fork 继续遵循 GPL-3.0 License。使用、修改和分发时请遵守原项目许可证要求，并保留上游作者署名。
