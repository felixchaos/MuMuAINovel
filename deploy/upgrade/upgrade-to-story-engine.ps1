param(
    [string]$Image = "felixchaos/mumuainovel:v1.4.8-story-engine.1",
    [string]$Version = "v1.4.8-story-engine.1",
    [string]$Branch = "codex/official-compatible-story-engine",
    [string]$Proxy = "",
    [switch]$Yes,
    [switch]$NoDbBackup,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$RawBase = "https://raw.githubusercontent.com/felixchaos/MuMuAINovel/$Branch"
$ComposeUrl = "$RawBase/deploy/dockerhub/docker-compose.yml"
$EnvUrl = "$RawBase/deploy/dockerhub/.env.example"

function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    docker compose @Args
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose failed: $($Args -join ' ')"
    }
}

function Test-ComposeAvailable {
    docker compose version *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose is not available. Install Docker Desktop first."
    }
}

function Read-EnvValue {
    param([string]$Key, [string]$Default)
    if (Test-Path ".env") {
        $line = Get-Content ".env" | Where-Object { $_ -match "^$([regex]::Escape($Key))=" } | Select-Object -Last 1
        if ($line) {
            $value = ($line -replace "^$([regex]::Escape($Key))=", "").TrimEnd("`r")
            if ($value.Length -ge 2 -and (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'")))) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            return $value
        }
    }
    return $Default
}

function Set-EnvValue {
    param([string]$Key, [string]$Value)
    if (-not (Test-Path ".env")) {
        New-Item -ItemType File -Path ".env" | Out-Null
    }

    $lines = Get-Content ".env"
    $found = $false
    $updated = foreach ($line in $lines) {
        if ($line -match "^$([regex]::Escape($Key))=") {
            $found = $true
            "$Key=$Value"
        } else {
            $line
        }
    }
    if (-not $found) {
        $updated += ""
        $updated += "$Key=$Value"
    }
    Set-Content -Path ".env" -Value $updated -Encoding UTF8
}

function Download-File {
    param([string]$Url, [string]$Path)
    Invoke-WebRequest -Uri $Url -OutFile $Path -UseBasicParsing
}

if ($Proxy) {
    $env:HTTP_PROXY = $Proxy
    $env:HTTPS_PROXY = $Proxy
    $env:http_proxy = $Proxy
    $env:https_proxy = $Proxy
}

Test-ComposeAvailable
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker daemon is not running. Start Docker Desktop first."
}

$ComposeFile = $null
foreach ($candidate in @("docker-compose.yml", "compose.yml", "compose.yaml")) {
    if (Test-Path $candidate) {
        $ComposeFile = $candidate
        break
    }
}

if (-not $ComposeFile) {
    throw "No docker-compose.yml/compose.yml found. Run this script inside the existing MuMuAINovel deployment directory."
}

$BackupDir = Join-Path "backups" ("upgrade-story-engine-" + (Get-Date -Format "yyyyMMdd-HHmmss"))

Write-Host "Current directory: $(Get-Location)"
Write-Host "Compose file:      $ComposeFile"
Write-Host "Target image:      $Image"
Write-Host "Backup dir:        $BackupDir"
Write-Host "Proxy:             $(if ($Proxy) { $Proxy } else { '<none>' })"

if ($DryRun) {
    Write-Host "Dry run complete. No files changed."
    exit 0
}

if (-not $Yes) {
    $answer = Read-Host "This will replace $ComposeFile with the story-engine Docker Hub compose file, preserving .env and Docker volumes. Continue? [y/N]"
    if ($answer -notin @("y", "Y", "yes", "YES")) {
        Write-Host "Cancelled."
        exit 0
    }
}

New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
Copy-Item $ComposeFile (Join-Path $BackupDir "$ComposeFile.bak") -Force

if (Test-Path ".env") {
    Copy-Item ".env" (Join-Path $BackupDir ".env.bak") -Force
} else {
    Download-File $EnvUrl ".env"
    Copy-Item ".env" (Join-Path $BackupDir ".env.generated.bak") -Force
}

try {
    docker compose -f $ComposeFile ps | Out-File (Join-Path $BackupDir "compose-ps-before.txt") -Encoding UTF8
} catch {}
try {
    docker volume ls | Out-File (Join-Path $BackupDir "docker-volumes-before.txt") -Encoding UTF8
} catch {}

$PostgresDb = Read-EnvValue "POSTGRES_DB" "mumuai_novel"
$PostgresUser = Read-EnvValue "POSTGRES_USER" "mumuai"

if (-not $NoDbBackup) {
    $PostgresCid = docker compose -f $ComposeFile ps -q postgres
    if ($PostgresCid) {
        Write-Host "Creating PostgreSQL SQL backup..."
        $BackupSql = Join-Path $BackupDir "postgres.sql"
        cmd /c "docker compose -f `"$ComposeFile`" exec -T postgres pg_dump -U `"$PostgresUser`" -d `"$PostgresDb`" > `"$BackupSql`""
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Database backup saved: $BackupSql"
        } else {
            Write-Warning "PostgreSQL backup failed. File backups are still available in $BackupDir."
            if (-not $Yes) {
                $answer = Read-Host "Continue without database dump? [y/N]"
                if ($answer -notin @("y", "Y", "yes", "YES")) {
                    throw "Cancelled."
                }
            }
        }
    } else {
        Write-Host "PostgreSQL service is not currently running; skipping pg_dump backup."
    }
} else {
    Write-Host "Skipping PostgreSQL backup by request."
}

$TempCompose = New-TemporaryFile
Download-File $ComposeUrl $TempCompose.FullName
Copy-Item $TempCompose.FullName $ComposeFile -Force
Remove-Item $TempCompose.FullName -Force

Set-EnvValue "MUMUAINOVEL_IMAGE" $Image
Set-EnvValue "APP_VERSION" ($Version -replace "^v", "")

$NoProxy = Read-EnvValue "NO_PROXY" ""
if (-not $NoProxy) {
    Set-EnvValue "NO_PROXY" "localhost,127.0.0.1,postgres,host.docker.internal"
} elseif ($NoProxy -notmatch "postgres") {
    Set-EnvValue "NO_PROXY" "$NoProxy,postgres,host.docker.internal"
}

Write-Host "Pulling target images..."
Invoke-Compose -f $ComposeFile pull

Write-Host "Starting upgraded services..."
Invoke-Compose -f $ComposeFile up -d --remove-orphans

Invoke-Compose -f $ComposeFile ps

$AppPort = Read-EnvValue "APP_PORT" "8000"
Write-Host ""
Write-Host "Upgrade complete."
Write-Host "Open: http://localhost:$AppPort"
Write-Host "Backups: $BackupDir"
Write-Host ""
Write-Host "Rollback compose file only:"
Write-Host "  Copy-Item '$BackupDir/$ComposeFile.bak' '$ComposeFile' -Force"
Write-Host "  docker compose -f '$ComposeFile' up -d"
Write-Host ""
Write-Host "Do not run docker compose down -v unless you intentionally want to delete database volumes."
