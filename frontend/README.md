# MuMuAINovel Frontend

这是 MuMuAINovel 的 React + TypeScript + Vite 前端。生产构建默认输出到 `backend/static`，由 FastAPI 后端统一托管。

## 开发

```bash
npm install
npm run dev
```

默认开发地址：

```text
http://localhost:5173
```

Vite 已配置代理：

- `/api` -> `http://localhost:8000`
- `/generated-assets` -> `http://localhost:8000`

因此本地开发时需要同时启动后端。

## 构建

```bash
npm run build
```

默认输出目录：

```text
../backend/static
```

Docker 构建时会临时把输出目录改为镜像内的 `dist`，再复制到后端静态目录。

## 功能开关

以下变量是构建期变量，改动后必须重新构建。

```bash
VITE_ENABLE_SPONSOR=false
VITE_ENABLE_ANNOUNCEMENT_MODAL=false
VITE_ENABLE_MUMU_API_LINKS=false
VITE_ENABLE_SPRING_FESTIVAL=false
```

含义：

- `VITE_ENABLE_SPONSOR=false`：隐藏赞助入口。
- `VITE_ENABLE_ANNOUNCEMENT_MODAL=false`：关闭公告弹窗。
- `VITE_ENABLE_MUMU_API_LINKS=false`：隐藏 MuMu API 外链。
- `VITE_ENABLE_SPRING_FESTIVAL=false`：关闭节日挂件。

示例：

```bash
VITE_ENABLE_SPONSOR=false \
VITE_ENABLE_ANNOUNCEMENT_MODAL=false \
VITE_ENABLE_MUMU_API_LINKS=false \
VITE_ENABLE_SPRING_FESTIVAL=false \
npm run build
```

## 常用命令

```bash
npm run dev
npm run build
npm run lint
npm run preview
```

## 注意事项

- 不要提交 `dist`、`node_modules` 或本地缓存目录。
- 不要在前端代码里写死 API Key、SMTP 密钥、Cloudflare Token 或个人服务器地址。
- 文本润色、章节重写、大纲续写等功能依赖后端 AI 配置；前端只负责采集参数和展示结果。
