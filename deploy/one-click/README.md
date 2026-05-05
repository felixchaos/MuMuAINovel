# MuMuAINovel Story Engine 一键部署包

这个目录提供 Windows 11 和 macOS 的双击部署入口。部署包是完整源码包，运行脚本会自动生成本机 `.env`，不会要求用户提前会 Git、Node、Python 或数据库命令。

## Windows 11

1. 解压 release 里的 `MuMuAINovel-StoryEngine-OneClick-*.zip`。
2. 双击 `deploy/one-click/MuMuAINovel-OneClick-Windows.bat`。
3. 终端出现后按提示选择“直接启动”或“引导配置”。
4. 启动成功后访问 `http://localhost:8000`。

如果电脑没有 Docker Desktop，脚本会尝试用 `winget` 安装；系统可能弹出管理员授权或要求重启，这是 Windows/Docker 的系统限制。

## macOS

1. 解压 release 里的 `MuMuAINovel-StoryEngine-OneClick-*.zip`。
2. 双击 `deploy/one-click/MuMuAINovel-OneClick-macOS.command`。
3. 如果 macOS 阻止运行，右键文件，选择“打开”。
4. 终端出现后按提示选择“直接启动”或“引导配置”。
5. 启动成功后访问 `http://localhost:8000`。

如果电脑没有 Docker Desktop，脚本会尝试通过 Homebrew 安装；没有 Homebrew 时会打开 Docker Desktop 下载页。

## 配置与代理

- 第一次运行会生成 `.env` 和 `.oneclick/oneclick.env`。
- 再次运行会自动复用已有配置并直接启动。
- 如果 GitHub、Docker 或依赖下载很慢，选择代理模式，输入局域网代理端口，例如 `7890`、`7897`、`10809`。
- 如果 API Key、SMTP、注册开关等可以在网页中配置，可以一路回车跳过。

默认本地管理员账号为 `admin / admin123`。部署给朋友使用时，建议首次登录后尽快修改管理员密码。
