$ErrorActionPreference = "Stop"

try {
  [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
  $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {}

$ForkVersion = "v1.4.8-story-engine.3"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = (Resolve-Path (Join-Path $ScriptDir "..\..\..")).Path
$EnvFile = Join-Path $RootDir ".env"
$StateDir = Join-Path $RootDir ".oneclick"
$StateFile = Join-Path $StateDir "oneclick.env"
$AppPortDefault = "8000"
$PostgresPortDefault = "5432"
$script:DockerProxyForBuild = ""

New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
Set-Location $RootDir

function Write-Log {
  param([string]$Message)
  Write-Host ""
  Write-Host ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $Message)
}

function Write-Tip {
  param([string]$Message)
  Write-Host ""
  Write-Host ("[提示] {0}" -f $Message) -ForegroundColor Yellow
}

function Read-Default {
  param(
    [string]$Prompt,
    [string]$Default = ""
  )
  if ([string]::IsNullOrWhiteSpace($Default)) {
    return (Read-Host $Prompt)
  }
  $answer = Read-Host "$Prompt [$Default]"
  if ([string]::IsNullOrWhiteSpace($answer)) {
    return $Default
  }
  return $answer
}

function Test-CommandExists {
  param([string]$Name)
  return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Write-Utf8NoBom {
  param(
    [string]$Path,
    [string]$Content
  )
  $encoding = New-Object System.Text.UTF8Encoding -ArgumentList $false
  [System.IO.File]::WriteAllText($Path, $Content, $encoding)
}

function New-RandomPassword {
  $chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789".ToCharArray()
  $rng = [System.Security.Cryptography.RNGCryptoServiceProvider]::Create()
  $bytes = New-Object byte[] 24
  $rng.GetBytes($bytes)
  $result = New-Object System.Text.StringBuilder
  foreach ($b in $bytes) {
    [void]$result.Append($chars[$b % $chars.Length])
  }
  return $result.ToString()
}

function Get-StateValue {
  param([string]$Key)
  if (!(Test-Path $StateFile)) { return "" }
  $line = Get-Content -Encoding UTF8 $StateFile | Where-Object { $_ -like "$Key=*" } | Select-Object -Last 1
  if (!$line) { return "" }
  return $line.Substring($Key.Length + 1)
}

function Set-StateValue {
  param(
    [string]$Key,
    [string]$Value
  )
  $lines = @()
  if (Test-Path $StateFile) {
    $lines = @(Get-Content -Encoding UTF8 $StateFile)
  }

  $done = $false
  $next = New-Object System.Collections.Generic.List[string]
  foreach ($line in $lines) {
    if ($line -like "$Key=*") {
      $next.Add("$Key=$Value")
      $done = $true
    } else {
      $next.Add($line)
    }
  }
  if (!$done) {
    $next.Add("$Key=$Value")
  }
  Write-Utf8NoBom $StateFile (($next -join "`n") + "`n")
}

function Get-EnvValue {
  param([string]$Key)
  if (!(Test-Path $EnvFile)) { return "" }
  $line = Get-Content -Encoding UTF8 $EnvFile | Where-Object { $_ -like "$Key=*" } | Select-Object -Last 1
  if (!$line) { return "" }
  return $line.Substring($Key.Length + 1)
}

function Set-EnvValue {
  param(
    [string]$Key,
    [string]$Value
  )
  $lines = @()
  if (Test-Path $EnvFile) {
    $lines = @(Get-Content -Encoding UTF8 $EnvFile)
  }

  $done = $false
  $next = New-Object System.Collections.Generic.List[string]
  foreach ($line in $lines) {
    if ($line -like "$Key=*") {
      $next.Add("$Key=$Value")
      $done = $true
    } else {
      $next.Add($line)
    }
  }
  if (!$done) {
    $next.Add("$Key=$Value")
  }
  Write-Utf8NoBom $EnvFile (($next -join "`n") + "`n")
}

function Write-DefaultEnv {
  $dbPassword = New-RandomPassword
  $appVersion = $ForkVersion.TrimStart("v")
  $content = @"
APP_NAME=MuMuAINovel
APP_VERSION=$appVersion
TZ=Asia/Shanghai
DEBUG=false

POSTGRES_DB=mumuai_novel
POSTGRES_USER=mumuai
POSTGRES_PASSWORD=$dbPassword
POSTGRES_PORT=$PostgresPortDefault

APP_PORT=$AppPortDefault
FRONTEND_URL=http://localhost:$AppPortDefault
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
"@
  Write-Utf8NoBom $EnvFile ($content + "`n")
}

function Configure-EnvInteractive {
  Write-Log "进入可选配置引导。所有项目都可以直接回车跳过。"

  $appPort = Read-Default "网页端口" ($(if (Get-EnvValue APP_PORT) { Get-EnvValue APP_PORT } else { $AppPortDefault }))
  $dbPort = Read-Default "PostgreSQL 本机端口" ($(if (Get-EnvValue POSTGRES_PORT) { Get-EnvValue POSTGRES_PORT } else { $PostgresPortDefault }))
  $adminUser = Read-Default "本地管理员账号" ($(if (Get-EnvValue LOCAL_AUTH_USERNAME) { Get-EnvValue LOCAL_AUTH_USERNAME } else { "admin" }))
  $adminPassword = Read-Default "本地管理员密码" ($(if (Get-EnvValue LOCAL_AUTH_PASSWORD) { Get-EnvValue LOCAL_AUTH_PASSWORD } else { "admin123" }))

  Set-EnvValue APP_PORT $appPort
  Set-EnvValue FRONTEND_URL "http://localhost:$appPort"
  Set-EnvValue POSTGRES_PORT $dbPort
  Set-EnvValue LOCAL_AUTH_USERNAME $adminUser
  Set-EnvValue LOCAL_AUTH_PASSWORD $adminPassword
  Set-EnvValue SESSION_COOKIE_SECURE "false"

  Write-Host ""
  Write-Host "AI 配置可以之后在网页 API 设置里填写。这里留空即跳过。"
  $aiProvider = Read-Default "默认 AI 提供商(openai/gemini/anthropic)" ($(if (Get-EnvValue DEFAULT_AI_PROVIDER) { Get-EnvValue DEFAULT_AI_PROVIDER } else { "openai" }))
  $model = Read-Default "默认模型名" ($(if (Get-EnvValue DEFAULT_MODEL) { Get-EnvValue DEFAULT_MODEL } else { "gpt-4o-mini" }))
  $apiKey = Read-Default "OpenAI/OpenRouter API Key，可留空" ""
  $baseUrl = Read-Default "OpenAI 兼容 API 地址" ($(if (Get-EnvValue OPENAI_BASE_URL) { Get-EnvValue OPENAI_BASE_URL } else { "https://api.openai.com/v1" }))

  Set-EnvValue DEFAULT_AI_PROVIDER $aiProvider
  Set-EnvValue DEFAULT_MODEL $model
  if (![string]::IsNullOrWhiteSpace($apiKey)) {
    Set-EnvValue OPENAI_API_KEY $apiKey
  }
  Set-EnvValue OPENAI_BASE_URL $baseUrl
}

function Test-Url {
  param([string]$Url)
  try {
    Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 10 | Out-Null
    return $true
  } catch {
    return $false
  }
}

function Configure-Proxy {
  param([bool]$Force = $false)

  $savedEnabled = Get-StateValue PROXY_ENABLED
  $savedHost = Get-StateValue PROXY_HOST
  $savedPort = Get-StateValue PROXY_PORT
  $proxyHost = ""
  $proxyPort = ""

  if (!$Force -and $savedEnabled -eq "true" -and $savedPort) {
    $answer = Read-Default "检测到已保存代理 $savedHost`:$savedPort，是否继续使用？(y/n)" "y"
    if ($answer -match "^(y|Y)$") {
      $proxyHost = $savedHost
      $proxyPort = $savedPort
    }
  }

  if (!$proxyPort) {
    if (!$Force -and (Test-Url "https://github.com")) {
      $answer = Read-Default "GitHub 访问正常，是否仍启用局域网代理？(y/n)" "n"
      if ($answer -notmatch "^(y|Y)$") {
        Set-StateValue PROXY_ENABLED "false"
        Set-EnvValue HTTP_PROXY ""
        Set-EnvValue HTTPS_PROXY ""
        return
      }
    } else {
      Write-Tip "GitHub 或依赖源访问可能较慢，建议启用局域网代理。"
    }

    $defaultHost = $(if ($savedHost) { $savedHost } else { "127.0.0.1" })
    $defaultPort = $(if ($savedPort) { $savedPort } else { "7890" })
    $proxyHost = Read-Default "代理主机，通常是 127.0.0.1" $defaultHost
    $proxyPort = Read-Default "代理端口，例如 7890/7897/10809" $defaultPort
  }

  $hostProxy = "http://$proxyHost`:$proxyPort"
  if ($proxyHost -eq "127.0.0.1" -or $proxyHost -eq "localhost") {
    $dockerProxy = "http://host.docker.internal:$proxyPort"
  } else {
    $dockerProxy = $hostProxy
  }

  $env:HTTP_PROXY = $hostProxy
  $env:HTTPS_PROXY = $hostProxy
  $env:ALL_PROXY = $hostProxy
  $env:http_proxy = $hostProxy
  $env:https_proxy = $hostProxy
  $env:all_proxy = $hostProxy
  $env:NO_PROXY = "localhost,127.0.0.1,postgres,host.docker.internal"
  $env:no_proxy = $env:NO_PROXY
  $script:DockerProxyForBuild = $dockerProxy

  Set-EnvValue HTTP_PROXY $dockerProxy
  Set-EnvValue HTTPS_PROXY $dockerProxy
  Set-EnvValue NO_PROXY "localhost,127.0.0.1,postgres,host.docker.internal"
  Set-StateValue PROXY_ENABLED "true"
  Set-StateValue PROXY_HOST $proxyHost
  Set-StateValue PROXY_PORT $proxyPort

  Write-Log "已启用代理：宿主机 $hostProxy，容器 $dockerProxy"
}

function Test-IsAdmin {
  $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
  $principal = New-Object Security.Principal.WindowsPrincipal($identity)
  return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Ensure-Docker {
  if (!(Test-CommandExists docker)) {
    Write-Tip "未检测到 Docker Desktop。"

    if (!(Test-IsAdmin)) {
      $elevate = Read-Default "安装 Docker/启用 WSL 可能需要管理员权限，是否用管理员权限重新打开本脚本？(y/n)" "y"
      if ($elevate -match "^(y|Y)$") {
        Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
        exit 0
      }
    }

    if (Test-CommandExists winget) {
      $install = Read-Default "是否使用 winget 安装 Docker Desktop？(y/n)" "y"
      if ($install -match "^(y|Y)$") {
        winget install -e --id Docker.DockerDesktop
      }
    } else {
      Start-Process "https://www.docker.com/products/docker-desktop/"
      Read-Host "请安装 Docker Desktop 并启动后，按回车继续"
    }
  }

  if (!(docker info 2>$null)) {
    Write-Tip "Docker Desktop 尚未启动，正在尝试打开。"
    $dockerPaths = @(
      "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe",
      "$env:LOCALAPPDATA\Docker\Docker Desktop.exe"
    )
    foreach ($path in $dockerPaths) {
      if (Test-Path $path) {
        Start-Process $path
        break
      }
    }
  }

  for ($i = 1; $i -le 90; $i++) {
    if (docker info 2>$null) {
      Write-Log "Docker 已就绪。"
      return
    }
    Write-Host "." -NoNewline
    Start-Sleep -Seconds 2
  }

  Write-Host ""
  throw "Docker Desktop 未就绪。请手动打开 Docker Desktop，等它显示 Running 后重新运行本脚本。"
}

function Invoke-Compose {
  & docker compose @args
  if ($LASTEXITCODE -ne 0) {
    throw "docker compose $($args -join ' ') 执行失败。"
  }
}

function Ensure-Compose {
  & docker compose version | Out-Null
  if ($LASTEXITCODE -ne 0) {
    throw "未检测到 docker compose。请更新 Docker Desktop 后重新运行。"
  }
}

function Build-AndStart {
  $mirrorDefault = Get-StateValue USE_CN_MIRROR
  if (!$mirrorDefault) { $mirrorDefault = "n" }
  $mirrorAnswer = Read-Default "是否启用国内构建镜像源以加速 npm/pip/apt？(y/n)" $mirrorDefault
  $useCnMirror = $(if ($mirrorAnswer -match "^(y|Y|true|TRUE)$") { "true" } else { "false" })
  Set-StateValue USE_CN_MIRROR $mirrorAnswer

  $buildArgs = @(
    "build",
    "--build-arg", "USE_CN_MIRROR=$useCnMirror",
    "--build-arg", "VITE_ENABLE_SPONSOR=false",
    "--build-arg", "VITE_ENABLE_ANNOUNCEMENT_MODAL=false",
    "--build-arg", "VITE_ENABLE_MUMU_API_LINKS=false",
    "--build-arg", "VITE_ENABLE_SPRING_FESTIVAL=false",
    "--build-arg", "VITE_DISABLE_PROMO_FEATURES=true",
    "--build-arg", "VITE_DEPLOY_PROFILE=oneclick"
  )

  if ($script:DockerProxyForBuild) {
    $buildArgs += @("--build-arg", "HTTP_PROXY=$script:DockerProxyForBuild", "--build-arg", "HTTPS_PROXY=$script:DockerProxyForBuild")
    $buildArgs += @("--build-arg", "http_proxy=$script:DockerProxyForBuild", "--build-arg", "https_proxy=$script:DockerProxyForBuild")
  }

  Write-Log "开始构建镜像。这一步首次运行会比较久。"
  $env:DOCKER_BUILDKIT = "1"
  Invoke-Compose @buildArgs

  Write-Log "启动服务。"
  Invoke-Compose up -d

  $appPort = Get-EnvValue APP_PORT
  if (!$appPort) { $appPort = $AppPortDefault }
  $healthUrl = "http://localhost:$appPort/health"

  Write-Log "等待服务健康检查。"
  for ($i = 1; $i -le 90; $i++) {
    if (Test-Url $healthUrl) {
      Write-Log "启动完成： http://localhost:$appPort"
      Start-Process "http://localhost:$appPort"
      Write-Host ""
      Write-Host "默认本地账号：admin / admin123（如果你在引导里改过，请使用新账号密码）"
      Write-Host "配置文件：$EnvFile"
      Write-Host "常用日志：docker compose logs -f"
      return
    }
    Write-Host "." -NoNewline
    Start-Sleep -Seconds 2
  }

  Write-Host ""
  Write-Tip "服务还没有通过健康检查，请查看日志：docker compose logs -f"
}

function Main {
  Write-Log "MuMuAINovel Story Engine 一键部署 $ForkVersion"

  if (Test-Path $EnvFile) {
    $choice = Read-Default "检测到已有 .env。回车直接启动，输入 c 重新配置，输入 p 设置代理，输入 q 退出" ""
    switch -Regex ($choice) {
      "^(q|Q)$" { return }
      "^(c|C)$" { Configure-EnvInteractive }
      "^(p|P)$" { Configure-Proxy $true }
      default {}
    }
  } else {
    Write-Host ""
    Write-Host "请选择启动方式："
    Write-Host "1. 完全跳过配置，使用默认本地配置启动"
    Write-Host "2. 进入可选配置引导"
    Write-Host "3. 先设置代理，再使用默认配置启动"
    $choice = Read-Default "输入序号" "1"
    Write-DefaultEnv
    switch ($choice) {
      "2" { Configure-EnvInteractive }
      "3" { Configure-Proxy $true }
      default {}
    }
  }

  Configure-Proxy $false
  Ensure-Docker
  Ensure-Compose
  Build-AndStart
}

try {
  Main
} catch {
  Write-Host ""
  Write-Host "部署失败：$($_.Exception.Message)" -ForegroundColor Red
  Write-Host "你可以重新运行本脚本，或在项目目录执行 docker compose logs -f 查看日志。"
  exit 1
}
