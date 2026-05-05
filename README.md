# MuMuAINovel Story Engine Fork

当前 fork 并行版本：`v1.4.8-story-engine.1`

官方兼容基线：`xiamuceer-j/MuMuAINovel v1.4.8`

基于 [xiamuceer-j/MuMuAINovel](https://github.com/xiamuceer-j/MuMuAINovel) 的个人增强版 fork，目标是在保持官方版本兼容性的基础上，补强长篇小说创作里的剧情工程能力、章节重写流程、后台任务可控性和多人部署体验。

本仓库不是官方发行版。需要最稳定的官方版本时，请优先查看上游仓库；需要本 fork 的增强功能时，可以按本文档从源码部署。

## 版本号策略

上游官方版本采用 `v主版本.次版本.修订号` 递增，例如当前兼容基线为 `v1.4.8`。本 fork 不占用官方后续版本号，而是在官方基线后追加分支通道和 fork 迭代号：

```text
v{官方基线版本}-story-engine.{fork迭代号}
```

当前版本 `v1.4.8-story-engine.1` 表示：

- `v1.4.8`：基于官方 `v1.4.8` 代码线，尽量保持官方数据结构、部署方式和工作流兼容。
- `story-engine`：本 fork 的主增强方向，聚焦剧情工程、拆书导入、实体预扫描、章节事实维护、重写上下文和后台任务收敛。
- `.1`：在该官方基线上的第 1 个公开 fork 迭代。

后续迭代规则：

- 只改本 fork 功能：递增 fork 迭代号，例如 `v1.4.8-story-engine.2`。
- 跟进新的官方版本：更新官方基线并重新开始 fork 迭代，例如 `v1.4.9-story-engine.1`。
- 涉及仅供本地部署的小修：优先记录在提交历史和更新日志中，必要时再提升 fork 迭代号。

应用内 `package.json` 仍保留官方兼容基线版本，用于兼容原有前端版本检查和官方生态；本 README 与 GitHub 分支说明使用上面的 fork 并行版本号。

## 这个 Fork 做了什么

这个 fork 的原则是“官方兼容优先，剧情工程增强在现有工作流上打通”。新增能力尽量复用官方已有的项目、章节、大纲、角色、组织、关系、伏笔、后台任务和 AI 调用基础设施，避免为了单点功能另起孤立体系。

### 官方兼容能力

- 保留官方核心功能：项目管理、世界观、角色/组织、章节、大纲、伏笔、提示词、MCP 插件、LinuxDO OAuth、本地账户登录。
- 继续使用官方兼容的数据表作为主要写入目标；故事工程能力优先从已有表派生或回写到已有表。
- 应用内版本与官方生态保持兼容；fork 差异通过 README、GitHub 分支和 release 版本说明表达。

### 拆书导入与章节质量

- TXT/Markdown 导入支持智能拆分、单章导入、批量导入和手动新建章节。
- 拆书预览会展示切分模式、置信度、异常原因和疑似边界，便于发现“看起来拆了但其实全错”的情况。
- 章节管理可以直接导入章节；冲突时支持跳过或覆盖，覆盖时会清理旧分析结果。
- 手动新建章节会强制补齐配位大纲，可以选择由 AI 根据正文生成大纲，也可以只创建基本信息。
- 章节导出支持范围选择和分章 ZIP，便于上传到写作平台。

### 剧情工程与事实维护

- 章节分析会沉淀结构化事实，覆盖人物、关系、地点、事件、组织变化和世界观声明，并按现有结构同步到角色、组织、关系、伏笔等模块。
- 引入实体预扫描：基于全文统计、首章出现位置、证据片段和命名模式生成候选人物、地点、组织、道具，减少主角识别错、凭空多角色和组织生成不稳。
- 引入名称权威与别名归一：过滤“大哥”“那人”“前辈”等不稳定泛称，角色合并、角色生成、问答和重写上下文共用同一套名字规则。
- 新增剧情工程视图入口：角色-章节出现矩阵、关系变化时间线、伏笔时间线、组织/世界观事件线，用于反哺后续写作与重写。

### AI 创作与重写

- 大纲生成/续写会补充前文、角色、组织、关系、职业和世界观上下文；解析失败时停止写库，避免坏 JSON 污染项目。
- 全章重写优先保持前文连贯性，再处理用户本次要求；上下文来自章节事实、角色卡、关系网、伏笔和相邻章节。
- 章节标题和摘要支持 AI 生成/润色；章节正文支持全文润色、全文重写和选中片段精准编辑。
- 文本框内润色支持填写用户要求、选择模型预设、流式展示结果，并在用户确认后才写回原表单。
- 角色、组织、关系、职业、大纲和世界观补全尽量走已有后台任务与 AI 调用链路。

### 后台任务、模型与成本参考

- 后台任务统一管理生命周期，支持运行中状态、取消、失败原因、重试和任务结果持久化。
- 章节分析、拆书预览、角色/组织优化、大纲优化等长任务不再依赖前端内存字典保存关键结果。
- API 调用记录 token 用量；OpenRouter 模型价格表每日缓存一次，作为参考价格展示，不作为真实计费依据。
- Gemini 空响应、安全拦截、URL 解析、模型列表和 JSON 容错错误会尽量透传可读原因，减少“秒失败但不知道为什么”。

### 部署与多人使用

- 管理员可以在网页里维护 SMTP、注册开关和系统级设置，适合个人或小团队自部署。
- AI Key 按用户配置；管理员可以只配置自己的 Key，朋友登录后可在 API 设置里自行配置。
- 更新日志读取本 fork 分支，方便看到当前增强版的实际提交。
- 提供 Windows/macOS 一键部署包：双击脚本后可跳过全部配置，也可按引导填写端口、管理员账号、API 和代理。

## 一键部署包

推荐给不熟悉命令行的用户使用 release 包：

1. 打开 [Releases](https://github.com/felixchaos/MuMuAINovel/releases)，下载 `MuMuAINovel-StoryEngine-OneClick-*.zip`。
2. 解压 zip。
3. Windows 11 双击 `deploy/one-click/MuMuAINovel-OneClick-Windows.bat`。
4. macOS 双击 `deploy/one-click/MuMuAINovel-OneClick-macOS.command`；如果系统阻止运行，右键选择“打开”。
5. 终端中可以一路回车跳过配置，脚本会使用默认本地配置启动。
6. 启动成功后访问 `http://localhost:8000`。

默认本地管理员账号：

```text
admin / admin123
```

一键脚本会自动生成 `.env` 和 `.oneclick/oneclick.env`。再次运行时会复用已有配置并智能启动；如果用户已经自己配置好了环境变量，也会优先使用现有 `.env`。

如果 GitHub、Docker 或依赖下载很慢，脚本会引导输入局域网代理端口，例如 `7890`、`7897`、`10809`，并自动为宿主机下载和 Docker 构建配置代理。

API Key、SMTP、注册开关等都可以在网页里配置；一键启动时可以全部跳过。真正必须具备的是 Docker Desktop，因为本项目通过 Docker Compose 启动数据库和应用。Windows/macOS 首次安装 Docker Desktop 时，系统可能弹出管理员授权或要求重启，这是操作系统和 Docker 的限制。

## 源码快速部署

熟悉命令行的用户可以使用 Docker Compose 从源码构建。不要直接使用官方 Docker Hub 镜像来部署本 fork，因为镜像可能不包含本 fork 的改动。

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

不会命令行的用户建议直接使用 release 中的一键部署包；脚本里已经包含代理和构建加速引导。

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
├── deploy/one-click/        # Windows/macOS 一键部署包入口
├── docker-compose.yml       # Docker Compose 编排
├── Dockerfile               # 前后端一体镜像构建
└── README.md
```

## 上游与许可证

上游项目：[xiamuceer-j/MuMuAINovel](https://github.com/xiamuceer-j/MuMuAINovel)

本 fork 继续遵循 GPL-3.0 License。使用、修改和分发时请遵守原项目许可证要求，并保留上游作者署名。
